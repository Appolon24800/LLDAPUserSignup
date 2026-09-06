"""All LLDAP operations, isolated from Flask so they are trivially mockable.

DN layout (LLDAP standard):
  users : uid=<username>,ou=people,<base>
  groups: cn=<name>,ou=groups,<base>   (attribute ``member`` holds user DNs)

TLS policy: ldaps:// connects with implicit TLS; ldap:// requires a
successful StartTLS *before* the bind so credentials never travel in
plaintext. Both cert validation and StartTLS can be skipped only via
LDAP_ALLOW_INSECURE (development / containerized test instances).
"""

from __future__ import annotations

import logging
import ssl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from ldap3 import NO_ATTRIBUTES, NONE, Connection, Server, Tls
from ldap3.core.exceptions import (
    LDAPBindError,
    LDAPException,
    LDAPNoSuchObjectResult,
)

USER_OU = "ou=people"
GROUP_OU = "ou=groups"
RECEIVE_TIMEOUT_SECONDS = 15

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # avoids a circular runtime import (lldap_api uses our errors)
    from .lldap_api import LldapGraphQL


class LdapServiceError(Exception):
    """Base class for LDAP failures surfaced to the API layer."""


class LdapConnectionError(LdapServiceError):
    """Could not connect / bind / upgrade to TLS."""


class UserAlreadyExistsError(LdapServiceError):
    def __init__(self, username: str) -> None:
        super().__init__(f"user {username!r} already exists")
        self.username = username


class GroupNotFoundError(LdapServiceError):
    def __init__(self, group: str) -> None:
        super().__init__(f"group {group!r} not found")
        self.group = group


@dataclass(frozen=True)
class Group:
    name: str
    members: int


ConnectionFactory = Callable[[], Iterator[Connection]]


class LdapService:
    def __init__(
        self,
        url: str,
        admin_dn: str,
        admin_password: str,
        base_dn: str,
        allow_insecure: bool = False,
        connection_factory: ConnectionFactory | None = None,
        ca_cert: str = "",
        graphql: LldapGraphQL | None = None,
    ) -> None:
        self.url = url
        self.admin_dn = admin_dn
        self.admin_password = admin_password
        self.base_dn = base_dn
        self.allow_insecure = allow_insecure
        self.ca_cert = ca_cert
        self.graphql = graphql
        self._connection_factory = connection_factory or self._default_connection

    # -- connection handling ---------------------------------------------------

    @property
    def _scheme(self) -> str:
        return urlparse(self.url).scheme.lower()

    @contextmanager
    def _default_connection(self) -> Iterator[Connection]:
        scheme = self._scheme
        if self.allow_insecure:
            tls = None
        else:
            # ca_certs_file makes ldap3 use create_default_context(cafile=...);
            # without it the system trust store applies (SSL_CERT_FILE honored).
            tls_kwargs = {"validate": ssl.CERT_REQUIRED}
            if self.ca_cert:
                tls_kwargs["ca_certs_file"] = self.ca_cert
            tls = Tls(**tls_kwargs)
        try:
            server = Server(
                urlparse(self.url).netloc,
                port=urlparse(self.url).port,
                use_ssl=scheme == "ldaps",
                tls=tls,
                connect_timeout=RECEIVE_TIMEOUT_SECONDS,
                # Skip the DSE/schema download on every connection: LLDAP
                # serves it slowly and the app never consults the schema.
                get_info=NONE,
            )
            conn = Connection(
                server,
                user=self.admin_dn,
                password=self.admin_password,
                auto_bind=scheme == "ldaps",
                raise_exceptions=True,
                receive_timeout=RECEIVE_TIMEOUT_SECONDS,
            )
            if scheme == "ldap":
                if not self.allow_insecure:
                    # StartTLS before bind: the admin password must never go
                    # over the wire unencrypted.
                    conn.start_tls(read_server_info=False)
                conn.bind()
            try:
                yield conn
            finally:
                conn.unbind()
        except LDAPBindError as err:
            raise LdapConnectionError(f"LDAP bind failed: {err}") from err
        except LDAPNoSuchObjectResult:
            raise  # a legitimate "entry absent" answer, not a failure
        except LDAPException as err:
            raise LdapConnectionError(f"LDAP connection failed: {err}") from err

    # -- DN helpers ---------------------------------------------------------------

    def user_dn(self, username: str) -> str:
        return f"uid={username},{USER_OU},{self.base_dn}"

    def group_dn(self, group: str) -> str:
        return f"cn={group},{GROUP_OU},{self.base_dn}"

    # -- operations ------------------------------------------------------------------

    def user_exists(self, username: str) -> bool:
        # No attributes requested: "dn" is not a real attribute type and
        # ldap3 validates requested attributes against the server schema.
        try:
            with self._connection_factory() as conn:
                return conn.search(
                    search_base=self.user_dn(username),
                    search_filter="(objectClass=*)",
                    search_scope="BASE",
                    attributes=NO_ATTRIBUTES,
                )
        except LDAPNoSuchObjectResult:
            return False  # base DN absent -> the user does not exist

    def create_user(
        self,
        username: str,
        password: str,
        first_name: str,
        last_name: str,
        display_name: str,
        email: str,
        photo_jpeg: bytes | None = None,
    ) -> None:
        attributes = {
            "objectClass": ["inetOrgPerson"],
            "uid": username,
            "cn": display_name,
            "sn": last_name,
            "givenName": first_name,
            "mail": email,
            "userPassword": password,
        }
        if photo_jpeg is not None:
            attributes["jpegPhoto"] = photo_jpeg
        try:
            with self._connection_factory() as conn:
                if not conn.add(self.user_dn(username), attributes=attributes):
                    description = str(conn.result.get("description", "")).lower()
                    if "alreadyexists" in description:
                        raise UserAlreadyExistsError(username)
                    raise LdapServiceError(
                        f"user creation failed: {conn.result.get('description', 'unknown')}"
                    )
        except LDAPException as err:
            if "alreadyexists" in str(err).lower():
                raise UserAlreadyExistsError(username) from err
            raise LdapServiceError(f"user creation failed: {err}") from err

    def delete_user(self, username: str) -> None:
        """Remove a user entry (rollback path; best effort)."""
        try:
            with self._connection_factory() as conn:
                conn.delete(self.user_dn(username))
        except LDAPException as err:
            raise LdapServiceError(f"user deletion failed: {err}") from err

    def add_to_groups(self, username: str, groups: list[str] | tuple[str, ...]) -> None:
        """Add the user to the given groups.

        LLDAP's LDAP interface cannot modify groups, so membership goes
        through the GraphQL API (see app.lldap_api). api must be provided
        by deployments; mocks/tests inject their own behavior.
        """
        if self.graphql is None:
            raise LdapServiceError(
                "group membership requires LLDAP_HTTP_URL (LLDAP GraphQL API)"
            )
        last_error: Exception | None = None
        for group in groups:
            try:
                self.graphql.add_user_to_group(username, group)
            except LdapServiceError as err:
                last_error = err
                logger.warning("adding %s to group %s failed: %s", username, group, err)
        if last_error:
            raise LdapServiceError(f"group membership update failed: {last_error}")

    def list_groups(self) -> list[Group]:
        """Groups with member counts, most-populated first (ties by name).

        One search covers every group: member is a multi-valued attribute
        holding user DNs, so its value count is the membership size.
        """
        try:
            with self._connection_factory() as conn:
                ok = conn.search(
                    search_base=f"{GROUP_OU},{self.base_dn}",
                    search_filter="(objectClass=*)",
                    search_scope="SUBTREE",
                    attributes=["cn", "member"],
                )
                if not ok:
                    return []
                groups: list[Group] = []
                for entry in conn.entries:
                    if "cn" not in entry.entry_attributes:
                        continue
                    members = 0
                    if "member" in entry.entry_attributes:
                        try:
                            members = len(entry.member.values)
                        except Exception:  # unreadable/absent member values
                            members = 0
                    groups.append(Group(name=str(entry.cn.value), members=members))
                groups.sort(key=lambda g: (-g.members, g.name))
                return groups
        except LDAPException as err:
            raise LdapServiceError(f"group listing failed: {err}") from err
