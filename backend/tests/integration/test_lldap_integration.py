"""Integration tests against a real (containerized) LLDAP instance.

Skipped unless INTEGRATION_LLDAP_URL is set. CI runs these against an
lldap/lldap service container; they verify the LDAP schema assumptions
(DNs, objectClasses, member attribute) that the mock tests cannot.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

from app.ldap_service import LdapService, UserAlreadyExistsError
from app.lldap_api import LldapGraphQL, admin_user_from_dn

pytestmark = pytest.mark.skipif(
    not os.environ.get("INTEGRATION_LLDAP_URL"), reason="no integration LLDAP configured"
)


@pytest.fixture(scope="session", autouse=True)
def wait_for_lldap():
    """LLDAP takes a variable time to accept connections; poll until ready."""
    deadline = time.monotonic() + 120
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            service().list_groups()
            return
        except Exception as err:  # readiness polling: keep trying
            last_error = err
            time.sleep(3)
    raise RuntimeError(f"LLDAP not ready after 120s: {last_error}")


def service() -> LdapService:
    return LdapService(
        url=os.environ["INTEGRATION_LLDAP_URL"],
        admin_dn=os.environ["INTEGRATION_ADMIN_DN"],
        admin_password=os.environ["INTEGRATION_ADMIN_PASSWORD"],
        base_dn=os.environ["INTEGRATION_BASE_DN"],
        allow_insecure=True,  # container-to-container plaintext, CI only
        graphql=LldapGraphQL(
            base_url=os.environ["INTEGRATION_LLDAP_HTTP_URL"],
            username=admin_user_from_dn(os.environ["INTEGRATION_ADMIN_DN"]),
            password=os.environ["INTEGRATION_ADMIN_PASSWORD"],
        ),
    )


def test_list_groups():
    groups = service().list_groups()
    assert groups, "expected at least the default lldap_admin group"


def test_user_lifecycle():
    username = f"it-{uuid.uuid4().hex[:10]}"
    assert service().user_exists(username) is False
    service().create_user(
        username,
        password="Phrase-Harbor7-Velvet",
        first_name="Test",
        last_name="User",
        display_name="Test User",
        email=f"{username}@example.com",
        photo_jpeg=b"\xff\xd8\xff\xe0integration",
    )
    assert service().user_exists(username) is True
    # The avatar travels through the GraphQL API, not the LDAP ADD.
    service().graphql.upload_avatar(username, b"\xff\xd8\xff\xe0integration")

    with pytest.raises(UserAlreadyExistsError):
        service().create_user(
            username,
            password="x",
            first_name="T",
            last_name="U",
            display_name="T U",
            email="t@example.com",
        )

    service().delete_user(username)
    assert service().user_exists(username) is False


def test_group_membership():
    username = f"it-{uuid.uuid4().hex[:10]}"
    group = service().list_groups()[0].name
    service().create_user(
        username,
        password="Phrase-Harbor7-Velvet",
        first_name="Test",
        last_name="Groups",
        display_name="Test Groups",
        email=f"{username}@example.com",
    )
    service().add_to_groups(username, [group])
    service().delete_user(username)
