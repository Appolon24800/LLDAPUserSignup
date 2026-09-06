"""Group membership via LLDAP's GraphQL HTTP API.

LLDAP's LDAP interface can create/delete/search users but does NOT support
modifying groups (its modify handler only accepts user DNs), so adding a
new user to the invite's groups goes through the GraphQL API instead:
login with the admin credentials, resolve the group's numeric id, then
addUserToGroup. Standard library only; failures raise LdapServiceError so
the registration flow treats them like any other directory failure.

Schema notes (lldap schema.graphql): `groups: [Group!]!` takes no filters,
so group ids are resolved by listing groups and matching displayName;
`addUserToGroup(userId: String!, groupId: Int!): Success` with
`Success { ok }`.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from contextlib import suppress

from .ldap_service import LdapServiceError

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10

_LOGIN = "/auth/simple/login"
_GRAPHQL = "/api/graphql"

_GROUPS_QUERY = """
query Groups {
  groups {
    id
    displayName
  }
}
"""

_ADD_MEMBER_MUTATION = """
mutation AddMember($user: String!, $group: Int!) {
  addUserToGroup(userId: $user, groupId: $group) {
    ok
  }
}
"""


class LldapGraphQL:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: int = TIMEOUT_SECONDS,
        post=None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        # Injectable HTTP POST for tests: post(url, payload, headers) -> body dict.
        self._post = post or self._http_post
        self._token: str | None = None
        self._token_expiry: float = 0.0

    # -- public API -------------------------------------------------------------

    def add_user_to_group(self, user_id: str, group_name: str) -> None:
        group_id = self._group_id(group_name)
        result = self._gql(_ADD_MEMBER_MUTATION, {"user": user_id, "group": group_id})
        if not result.get("addUserToGroup", {}).get("ok", False):
            raise LdapServiceError(f"adding {user_id!r} to group {group_name!r} failed")

    # -- internals ----------------------------------------------------------------

    def _group_id(self, name: str) -> int:
        result = self._gql(_GROUPS_QUERY, {})
        for group in result.get("groups") or []:
            if group.get("displayName") == name:
                return int(group["id"])
        raise LdapServiceError(f"group {name!r} not found")

    def _gql(self, query: str, variables: dict) -> dict:
        token = self._get_token()
        body = self._post(
            f"{self.base_url}{_GRAPHQL}",
            {"query": query, "variables": variables},
            {"Authorization": f"Bearer {token}"},
        )
        if body.get("errors"):
            raise LdapServiceError(f"GraphQL error: {body['errors']}")
        return body.get("data") or {}

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry:
            return self._token
        try:
            body = self._post(
                f"{self.base_url}{_LOGIN}",
                {"username": self.username, "password": self.password},
                {},
            )
        except LdapServiceError:
            raise
        except Exception as err:  # transport failures become service errors
            raise LdapServiceError(f"LLDAP API unreachable: {err}") from err
        token = body.get("token")
        if not token:
            raise LdapServiceError("LLDAP login returned no token")
        self._token = token
        self._token_expiry = _jwt_expiry(token) - 60  # refresh a minute early
        if self._token_expiry <= time.time():
            self._token_expiry = time.time() + 300  # unreadable exp: conservative
        return token

    def _http_post(self, url: str, payload: dict, headers: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - operator-configured URL
            url,
            data=data,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            detail = ""
            with suppress(Exception):
                detail = err.read().decode("utf-8", "replace")[:200]
            raise LdapServiceError(f"LLDAP API HTTP {err.code}: {detail}") from err
        except Exception as err:
            logger.warning("LLDAP API request to %s failed: %s", url, err)
            raise LdapServiceError(f"LLDAP API unreachable: {err}") from err


def _jwt_expiry(token: str) -> float:
    """Best-effort `exp` claim read; returns 0 when undecodable."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return float(payload.get("exp", 0))
    except Exception:
        return 0.0


def derive_http_url(ldap_url: str) -> str:
    """Default the API URL from LDAP_URL: same host, LLDAP's port 17170.

    ldaps deployments get https (LLDAP shares the TLS cert); plain ldap
    gets http.
    """
    from urllib.parse import urlparse

    parsed = urlparse(ldap_url)
    scheme = "https" if parsed.scheme == "ldaps" else "http"
    return f"{scheme}://{parsed.hostname}:17170"


def admin_user_from_dn(dn: str) -> str:
    """Extract the login username from a bind DN's first component.

    Accepts any RDN attribute (uid=admin,... or cn=svc-account,...); the
    LDAP bind takes the full DN, but the HTTP login wants the bare value.
    """
    first = dn.split(",")[0].strip()
    if "=" in first:
        return first.split("=", 1)[1].strip()
    return dn
