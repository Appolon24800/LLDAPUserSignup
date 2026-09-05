"""Integration tests against a real (containerized) LLDAP instance.

Skipped unless INTEGRATION_LLDAP_URL is set. CI runs these against an
lldap/lldap service container; they verify the LDAP schema assumptions
(DNs, objectClasses, member attribute) that the mock tests cannot.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.ldap_service import LdapService, UserAlreadyExistsError

pytestmark = pytest.mark.skipif(
    not os.environ.get("INTEGRATION_LLDAP_URL"), reason="no integration LLDAP configured"
)


@pytest.fixture()
def service():
    return LdapService(
        url=os.environ["INTEGRATION_LLDAP_URL"],
        admin_dn=os.environ["INTEGRATION_ADMIN_DN"],
        admin_password=os.environ["INTEGRATION_ADMIN_PASSWORD"],
        base_dn=os.environ["INTEGRATION_BASE_DN"],
        allow_insecure=True,  # container-to-container plaintext, CI only
    )


def test_list_groups(service):
    groups = service.list_groups()
    assert groups, "expected at least the default lldap_admin group"


def test_user_lifecycle(service):
    username = f"it-{uuid.uuid4().hex[:10]}"
    assert service.user_exists(username) is False
    service.create_user(
        username,
        password="Phrase-Harbor7-Velvet",
        first_name="Test",
        last_name="User",
        display_name="Test User",
        email=f"{username}@example.com",
        photo_jpeg=b"\xff\xd8\xff\xe0integration",
    )
    assert service.user_exists(username) is True

    with pytest.raises(UserAlreadyExistsError):
        service.create_user(
            username,
            password="x",
            first_name="T",
            last_name="U",
            display_name="T U",
            email="t@example.com",
        )

    service.delete_user(username)
    assert service.user_exists(username) is False


def test_group_membership(service):
    username = f"it-{uuid.uuid4().hex[:10]}"
    group = service.list_groups()[0]
    service.create_user(
        username,
        password="Phrase-Harbor7-Velvet",
        first_name="Test",
        last_name="Groups",
        display_name="Test Groups",
        email=f"{username}@example.com",
    )
    service.add_to_groups(username, [group])
    service.delete_user(username)
