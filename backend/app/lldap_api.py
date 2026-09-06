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
import uuid
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

_AVATAR_MUTATION = """
mutation Avatar($user: String!, $raw: Upload!) {
  uploadAvatar(userId: $user, raw: $raw) {
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
        post_raw=None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        # Injectable HTTP POSTs for tests: post(url, payload, headers) takes a
        # JSON dict; post_raw(url, body_bytes, headers) is the multipart path.
        self._post = post or self._http_post
        self._post_raw = post_raw or self._http_post_raw
        self._token: str | None = None
        self._token_expiry: float = 0.0

    # -- public API -------------------------------------------------------------

    def add_user_to_group(self, user_id: str, group_name: str) -> None:
        group_id = self._group_id(group_name)
        result = self._gql(_ADD_MEMBER_MUTATION, {"user": user_id, "group": group_id})
        if not result.get("addUserToGroup", {}).get("ok", False):
            raise LdapServiceError(f"adding {user_id!r} to group {group_name!r} failed")

    def upload_avatar(self, user_id: str, jpeg: bytes) -> None:
        """Set the user's avatar (GraphQL multipart upload spec).

        Some LLDAP builds reject a binary jpegPhoto attribute on the LDAP
        ADD (UTF-8 constraint), so the avatar goes through the API instead.
        """
        token = self._get_token()
        operations = json.dumps(
            {"query": _AVATAR_MUTATION, "variables": {"user": user_id, "raw": None}}
        )
        mapping = json.dumps({"0": ["variables.raw"]})
        body, content_type = _multipart(
            {"operations": operations, "map": mapping}, "0", "avatar.jpg", jpeg
        )
        result = self._post_raw(
            f"{self.base_url}{_GRAPHQL}",
            body,
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
            },
        )
        if result.get("errors"):
            raise LdapServiceError(f"GraphQL error: {result['errors']}")
        if not result.get("data", {}).get("uploadAvatar", {}).get("ok", False):
            raise LdapServiceError(f"avatar upload for {user_id!r} failed")

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

    def _http_post_raw(self, url: str, body: bytes, headers: dict) -> dict:
        request = urllib.request.Request(  # noqa: S310 - operator-configured URL
            url,
            data=body,
            headers=headers,
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
            logger.warning("LLDAP API upload to %s failed: %s", url, err)
            raise LdapServiceError(f"LLDAP API unreachable: {err}") from err


def _multipart(
    fields: dict[str, str], file_field: str, filename: str, content: bytes
) -> tuple[bytes, str]:
    """Build a multipart/form-data body (GraphQL single-file upload spec).

    JSON parts carry an explicit application/json content type: juniper's
    multipart parser rejects the request without it ("Content type error").
    """
    boundary = f"----lldapsignup{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n'
                f"Content-Type: application/json\r\n\r\n"
                f"{value}\r\n"
            ).encode()
        )
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{filename}"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        + content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


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
    """Extract the uid from a bind DN (uid=admin,ou=... -> admin)."""
    if dn.lower().startswith("uid="):
        return dn[4 : dn.index(",")] if "," in dn else dn[4:]
    return dn
