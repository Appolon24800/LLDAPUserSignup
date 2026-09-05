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

import ssl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from urllib.parse import urlparse

from ldap3 import MODIFY_ADD, Connection, Server, Tls
from ldap3.core.exceptions import LDAPBindError, LDAPException

USER_OU = "ou=people"
GROUP_OU = "ou=groups"
RECEIVE_TIMEOUT_SECONDS = 15


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
    ) -> None:
        self.url = url
        self.admin_dn = admin_dn
        self.admin_password = admin_password
        self.base_dn = base_dn
        self.allow_insecure = allow_insecure
        self._connection_factory = connection_factory or self._default_connection

    # -- connection handling ---------------------------------------------------

    @property
    def _scheme(self) -> str:
        return urlparse(self.url).scheme.lower()

    @contextmanager
    def _default_connection(self) -> Iterator[Connection]:
        scheme = self._scheme
        tls = Tls(validate=ssl.CERT_REQUIRED) if not self.allow_insecure else None
        try:
            server = Server(
                urlparse(self.url).netloc,
                port=urlparse(self.url).port,
                use_ssl=scheme == "ldaps",
                tls=tls,
                connect_timeout=RECEIVE_TIMEOUT_SECONDS,
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
        except LDAPException as err:
            raise LdapConnectionError(f"LDAP connection failed: {err}") from err

    # -- DN helpers ---------------------------------------------------------------

    def user_dn(self, username: str) -> str:
        return f"uid={username},{USER_OU},{self.base_dn}"

    def group_dn(self, group: str) -> str:
        return f"cn={group},{GROUP_OU},{self.base_dn}"

    # -- operations ------------------------------------------------------------------

    def user_exists(self, username: str) -> bool:
        with self._connection_factory() as conn:
            return conn.search(
                search_base=self.user_dn(username),
                search_filter="(objectClass=*)",
                search_scope="BASE",
                attributes=["dn"],
            )

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

    def add_to_groups(self, username: str, groups: list[str] | tuple[str, ...]) -> None:
        user_dn = self.user_dn(username)
        try:
            with self._connection_factory() as conn:
                for group in groups:
                    ok = conn.modify(
                        self.group_dn(group),
                        {"member": [(MODIFY_ADD, [user_dn])]},
                    )
                    if not ok:
                        raise GroupNotFoundError(group)
        except LdapServiceError:
            raise
        except LDAPException as err:
            raise LdapServiceError(f"group membership update failed: {err}") from err

    def list_groups(self) -> list[str]:
        try:
            with self._connection_factory() as conn:
                ok = conn.search(
                    search_base=f"{GROUP_OU},{self.base_dn}",
                    search_filter="(objectClass=*)",
                    search_scope="SUBTREE",
                    attributes=["cn"],
                )
                if not ok:
                    return []
                names = sorted(
                    {str(e.cn.value) for e in conn.entries if "cn" in e.entry_attributes}
                )
                return names
        except LDAPException as err:
            raise LdapServiceError(f"group listing failed: {err}") from err
