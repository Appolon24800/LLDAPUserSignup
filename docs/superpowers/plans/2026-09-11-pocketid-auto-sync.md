# PocketID Auto-Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a successful registration, automatically trigger PocketID's LDAP sync (fire-and-forget) so the new user can log in via PocketID within seconds instead of waiting for PocketID's hourly scheduled sync.

**Architecture:** Two new optional env vars (`POCKETID_URL`, `POCKETID_API_KEY`, both-or-neither) feed a new `backend/app/pocketid.py` module that structurally mirrors the existing Telegram `notifier.py`: a public `trigger_ldap_sync(config)` that no-ops when unconfigured and otherwise submits a single `POST {url}/api/application-configuration/sync-ldap` with an `X-API-Key` header to a one-worker background thread pool. The registration endpoint calls it right after success, next to the existing Telegram notification.

**Tech Stack:** Python 3.12, Flask backend, stdlib `urllib.request` only (no new dependencies), pytest with an injectable `send` seam.

**Spec:** `docs/superpowers/specs/2026-09-11-pocketid-auto-sync-design.md`

## Global Constraints

- Standard library only in the new module — no new pip dependencies (`requirements.txt` untouched).
- Fire-and-forget semantics: a PocketID outage, slowness, or misbehavior must never slow down or fail a registration; failures are logged (warning), never raised.
- `POCKETID_URL` and `POCKETID_API_KEY` are both-or-neither: exactly one set → `ConfigError` at startup; neither set → feature fully disabled, zero behavior change.
- `POCKETID_URL` validated as an absolute `http(s)` URL when set (same rule as `REDIRECT_URL`); trailing slash stripped.
- The API key is backend-env-only: never in the frontend bundle, never logged.
- All commands run from `backend/` (e.g. `cd backend && pytest tests/test_config.py -v`); lint with `ruff check .` before every commit.
- Conventional commits, lowercase, imperative (repo convention: `feat:`, `docs:`); English everywhere.
- Python 3.12 syntax (`from __future__ import annotations`, `X | None` unions) matching the surrounding code.

---

### Task 1: Config — `POCKETID_URL` / `POCKETID_API_KEY` pair

**Files:**
- Modify: `backend/app/config.py` (dataclass fields after line 109, validation block after line 173, kwargs in the `cls(...)` return after line 211)
- Test: `backend/tests/test_config.py` (new test after `test_redirect_url_optional_and_validated`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `Config.pocketid_url: str` and `Config.pocketid_api_key: str`, both defaulting to `""`. Later tasks read these fields; `Config.from_env` raises `ConfigError` mentioning `POCKETID_URL` / "must be set together" on bad input.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_config.py`, after `test_redirect_url_optional_and_validated`:

```python
def test_pocketid_optional_and_validated():
    both = {"POCKETID_URL": "https://id.example.com", "POCKETID_API_KEY": "pid-test-key"}
    cfg = Config.from_env(ENV | both)
    assert cfg.pocketid_url == "https://id.example.com"
    assert cfg.pocketid_api_key == "pid-test-key"
    # Defaults: feature off, both empty.
    assert Config.from_env(ENV).pocketid_url == ""
    assert Config.from_env(ENV).pocketid_api_key == ""
    # Trailing slash stripped, like BASE_URL.
    cfg = Config.from_env(ENV | {"POCKETID_URL": "https://id.example.com/",
                                 "POCKETID_API_KEY": "pid-test-key"})
    assert cfg.pocketid_url == "https://id.example.com"
    # Malformed URL.
    with pytest.raises(ConfigError, match="POCKETID_URL"):
        Config.from_env(ENV | {"POCKETID_URL": "id.example.com", "POCKETID_API_KEY": "k"})
    with pytest.raises(ConfigError, match="POCKETID_URL"):
        Config.from_env(ENV | {"POCKETID_URL": "ftp://id.example.com", "POCKETID_API_KEY": "k"})
    # Both-or-neither.
    with pytest.raises(ConfigError, match="must be set together"):
        Config.from_env(ENV | {"POCKETID_URL": "https://id.example.com"})
    with pytest.raises(ConfigError, match="must be set together"):
        Config.from_env(ENV | {"POCKETID_API_KEY": "pid-test-key"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_config.py::test_pocketid_optional_and_validated -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'pocketid_url'` (from_env ignores the unknown env vars, so the first field access fails).

- [ ] **Step 3: Implement**

In `backend/app/config.py`, add two dataclass fields immediately after `telegram_admin_ids: frozenset[int] = frozenset()` (currently line 109):

```python
    # Optional: when both are set, the backend asks PocketID to re-sync its
    # LDAP users right after a successful registration (PocketID otherwise
    # only syncs on startup and hourly). The key is an admin API key created
    # in PocketID at /settings/admin/api-keys.
    pocketid_url: str = ""
    pocketid_api_key: str = ""
```

In `Config.from_env`, after the `redirect_url` validation block (currently ends line 173) and before the `raw_notify_ids` line, add:

```python
        pocketid_url = env.get("POCKETID_URL", "").strip().rstrip("/")
        if pocketid_url:
            parsed = urlparse(pocketid_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ConfigError(
                    f"POCKETID_URL must be an absolute http(s) URL, got {pocketid_url!r}"
                )
        pocketid_api_key = env.get("POCKETID_API_KEY", "").strip()
        if bool(pocketid_url) != bool(pocketid_api_key):
            raise ConfigError(
                "POCKETID_URL and POCKETID_API_KEY must be set together "
                "(leave both empty to disable the PocketID sync trigger)"
            )
```

In the `return cls(...)` call, add after `lldap_admin_user=env.get("LLDAP_ADMIN_USER", "").strip(),` (currently line 211):

```python
            pocketid_url=pocketid_url,
            pocketid_api_key=pocketid_api_key,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ruff check . && pytest tests/test_config.py -v`
Expected: all PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat: add POCKETID_URL/POCKETID_API_KEY config pair (both-or-neither)"
```

---

### Task 2: `pocketid.py` — fire-and-forget sync trigger module

**Files:**
- Create: `backend/app/pocketid.py`
- Test: `backend/tests/test_pocketid.py`

**Interfaces:**
- Consumes: `Config.pocketid_url` and `Config.pocketid_api_key` from Task 1.
- Produces: `trigger_ldap_sync(config: Config, send: Callable[[str, str], None] | None = None) -> None` — no-op when either field is empty; otherwise `send(url, api_key)` exactly once. Module-level `_send(url: str, api_key: str) -> None` performs the HTTP POST and never raises. Constant `SYNC_PATH = "/api/application-configuration/sync-ldap"`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_pocketid.py`:

```python
"""PocketID LDAP sync trigger."""

from __future__ import annotations

from app.pocketid import trigger_ldap_sync
from tests.conftest import make_config


def pocketid_config(tmp_path, **overrides):
    overrides.setdefault("pocketid_url", "https://id.example.com")
    overrides.setdefault("pocketid_api_key", "pid-test-key")
    return make_config(tmp_path, **overrides)


class TestTriggerLdapSync:
    def test_sends_once_with_url_and_key(self, tmp_path):
        sent = []
        trigger_ldap_sync(
            pocketid_config(tmp_path),
            send=lambda url, key: sent.append((url, key)),
        )
        assert sent == [("https://id.example.com", "pid-test-key")]

    def test_disabled_without_url(self, tmp_path):
        sent = []
        trigger_ldap_sync(
            pocketid_config(tmp_path, pocketid_url=""),
            send=lambda url, key: sent.append((url, key)),
        )
        assert sent == []

    def test_disabled_without_api_key(self, tmp_path):
        sent = []
        trigger_ldap_sync(
            pocketid_config(tmp_path, pocketid_api_key=""),
            send=lambda url, key: sent.append((url, key)),
        )
        assert sent == []

    def test_production_sender_swallows_errors(self, monkeypatch):
        from app import pocketid

        def boom(request, timeout=None):
            raise OSError("network down")

        monkeypatch.setattr(pocketid.urllib.request, "urlopen", boom)
        pocketid._send("https://id.example.com", "pid-test-key")  # must not raise

    def test_production_sender_posts_sync_endpoint(self, monkeypatch):
        from app import pocketid

        calls = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b""

        def fake_urlopen(request, timeout=None):
            # urllib capitalizes header names: "X-API-Key" -> "X-api-key".
            calls.append(
                (request.full_url, request.get_method(), request.headers.get("X-api-key"))
            )
            return FakeResponse()

        monkeypatch.setattr(pocketid.urllib.request, "urlopen", fake_urlopen)
        pocketid._send("https://id.example.com", "pid-test-key")
        assert calls == [
            (
                "https://id.example.com/api/application-configuration/sync-ldap",
                "POST",
                "pid-test-key",
            )
        ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_pocketid.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pocketid'`.

- [ ] **Step 3: Implement**

Create `backend/app/pocketid.py`:

```python
"""Optional PocketID LDAP sync trigger when an account is created.

PocketID (with LDAP enabled) imports LDAP users on startup and hourly only;
without a nudge, a freshly registered user cannot log in via PocketID for up
to an hour. When POCKETID_URL and POCKETID_API_KEY are configured, the
backend asks PocketID to re-sync right after a successful registration:
POST {url}/api/application-configuration/sync-ldap authenticated with an
admin API key (X-API-Key header). Fire-and-forget from a background thread —
a PocketID outage must never slow down or fail a registration, and the
hourly scheduled sync remains the natural fallback. Standard library only.
"""

from __future__ import annotations

import logging
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

SYNC_PATH = "/api/application-configuration/sync-ldap"
TIMEOUT_SECONDS = 10

_executor: ThreadPoolExecutor | None = None


def trigger_ldap_sync(config: Config, send: Callable[[str, str], None] | None = None) -> None:
    """Ask PocketID to re-sync its LDAP users (no-op when unconfigured).

    `send` is injectable for tests; production uses the thread-pool sender.
    """
    if not config.pocketid_url or not config.pocketid_api_key:
        return
    if send is not None:
        send(config.pocketid_url, config.pocketid_api_key)
    else:
        _executor_submit(_send, config.pocketid_url, config.pocketid_api_key)


def _executor_submit(func, *args) -> None:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pocketid-sync")
    _executor.submit(func, *args)


def _send(url: str, api_key: str) -> None:
    request = urllib.request.Request(  # noqa: S310 - operator-configured URL
        f"{url}{SYNC_PATH}",
        headers={"X-API-Key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            response.read()
    except Exception:  # sync failures are logged, never raised
        logger.warning("PocketID LDAP sync trigger to %s failed", url, exc_info=True)
```

Note: `urllib` turns a non-2xx into `urllib.error.HTTPError`, so the single `except Exception` covers transport errors, HTTP errors and the 10 s timeout. A successful `204 No Content` raises nothing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ruff check . && pytest tests/test_pocketid.py -v`
Expected: 5 PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pocketid.py backend/tests/test_pocketid.py
git commit -m "feat: fire-and-forget PocketID LDAP sync trigger module"
```

---

### Task 3: Call site — trigger sync after successful registration

**Files:**
- Modify: `backend/app/api/public.py` (import block line 22, success block lines 244-246)
- Test: `backend/tests/test_api_public.py` (extend `test_register_happy_path`)

**Interfaces:**
- Consumes: `trigger_ldap_sync(config)` from Task 2.
- Produces: the registration endpoint now triggers the PocketID sync on success, before the Telegram notification. No other endpoint changes.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_api_public.py`, extend `test_register_happy_path` — add the patch next to the existing `notify_account_created` patch and the assertion at the end:

```python
def test_register_happy_path(client, fake_ldap, code, monkeypatch):
    from app.api import public

    notifications = []
    monkeypatch.setattr(
        public,
        "notify_account_created",
        lambda cfg, display_name: notifications.append(display_name),
    )
    syncs = []
    monkeypatch.setattr(
        public,
        "trigger_ldap_sync",
        lambda cfg: syncs.append(cfg),
    )
    res = register(client, code)
    assert res.status_code == 201
    assert res.get_json() == {"username": "alice", "created": True}
    created = fake_ldap.created[0]
    assert created["username"] == "alice"
    assert created["first_name"] == "Alice"
    assert created["last_name"] == "Smith"
    assert created["display_name"] == "Alice Smith"
    assert fake_ldap.group_adds == [("alice", ["family"])]
    assert notifications == ["Alice Smith"]  # display name, not username
    assert len(syncs) == 1  # PocketID sync triggered exactly once, with the app config
    # Code is single-use now.
    assert post_json(client, "/api/v1/validate-code", {"code": code}).status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_api_public.py::test_register_happy_path -v`
Expected: FAIL — `AttributeError: <module 'app.api.public'> does not have the attribute 'trigger_ldap_sync'` (monkeypatch refuses to set a nonexistent attribute).

- [ ] **Step 3: Implement**

In `backend/app/api/public.py`, add the import after the `notifier` import (line 22) — alphabetical order puts `pocketid` between `notifier` and `validation`:

```python
from ..pocketid import trigger_ldap_sync
```

In the success block of the registration handler (currently lines 244-246), insert the sync trigger between the lockout reset and the Telegram notification (queued first so it starts as early as possible — both are fire-and-forget):

```python
    _lockout().reset(request.remote_addr or "unknown")
    trigger_ldap_sync(_cfg())
    notify_account_created(_cfg(), display_name=full_name)
    return jsonify({"username": username, "created": True}), 201
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ruff check . && pytest -v`
Expected: the whole backend suite passes (all other registration tests use a config with empty PocketID fields, so the unpatched call is a no-op), ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/public.py backend/tests/test_api_public.py
git commit -m "feat: trigger PocketID LDAP sync after successful registration"
```

---

### Task 4: Docs — `.env.example`, `docker-compose.yml`, README

**Files:**
- Modify: `.env.example` (new section after the Telegram block, line 46)
- Modify: `docker-compose.yml` (backend `environment:`, after the `TELEGRAM_ADMIN_IDS` line 45)
- Modify: `README.md` (new paragraph after the "Registration notifications" paragraph, line 129)

**Interfaces:**
- Consumes: the env var names from Task 1.
- Produces: documentation only — no code interfaces.

- [ ] **Step 1: `.env.example`**

Insert after the `TELEGRAM_ADMIN_IDS=123456789` line (keeping one blank line between sections):

```dotenv

# --- PocketID (optional) ----------------------------------------------------------
# When both are set, the backend triggers PocketID's LDAP sync right after a
# successful registration, so the new user can log in via PocketID within
# seconds (PocketID otherwise syncs LDAP only on startup and hourly). The key
# is an admin API key created in PocketID at /settings/admin/api-keys.
# Leave both empty to disable.
POCKETID_URL=
POCKETID_API_KEY=
```

- [ ] **Step 2: `docker-compose.yml`**

In the `backend` service `environment:` mapping, add after `TELEGRAM_ADMIN_IDS: ${TELEGRAM_ADMIN_IDS}`:

```yaml
      # Optional: trigger PocketID's LDAP sync after each registration.
      POCKETID_URL: ${POCKETID_URL:-}
      POCKETID_API_KEY: ${POCKETID_API_KEY:-}
```

- [ ] **Step 3: README**

In `README.md`, immediately after the "Registration notifications" paragraph (which ends with "a Telegram outage never affects signups."), add:

```markdown
**PocketID sync**: when `POCKETID_URL` and `POCKETID_API_KEY` (an admin API
key created in PocketID's admin UI) are set, every successful registration
also asks PocketID to re-sync its LDAP users, so the new user can log in
through PocketID within seconds instead of waiting for the hourly scheduled
sync. The trigger is fire-and-forget — a PocketID outage never affects
signups, and the hourly sync picks up the user regardless.
```

- [ ] **Step 4: Verify nothing regressed**

Run: `cd backend && ruff check . && pytest` and `docker compose config --quiet`
Expected: tests pass, ruff clean, compose file still valid.

- [ ] **Step 5: Commit**

```bash
git add .env.example docker-compose.yml README.md
git commit -m "docs: document optional PocketID sync trigger (env, compose, README)"
```

---

### Task 5: Live verification (requires the real PocketID instance)

**Files:**
- None modified.

**Interfaces:**
- Consumes: the deployed PocketID instance and an admin API key. This task cannot be completed by an agent without network access to the instance — if unreachable, STOP and hand these steps to the user; do not mark complete.

- [ ] **Step 1: Verify the sync endpoint accepts the key**

```bash
curl -i -X POST -H "X-API-Key: <POCKETID_API_KEY>" \
  https://<pocketid-host>/api/application-configuration/sync-ldap
```

Expected: `HTTP/2 204` (or `HTTP/1.1 204 No Content`). `401/403` → the key is not an *admin* API key; regenerate at `/settings/admin/api-keys`.

- [ ] **Step 2: End-to-end**

Set `POCKETID_URL` and `POCKETID_API_KEY` in `.env`, `docker compose up -d --build backend`, register a throwaway user via a `/gen` link, and confirm the user appears in PocketID within a few seconds of the success screen (without clicking the manual sync button).

- [ ] **Step 3: Report**

No commit. Report the outcome (204 observed, user synced) — evidence before "done".

---

## Self-Review Notes

- Spec coverage: config validation (Task 1), module + no-op/injectable/fire-and-forget (Task 2), call site ordering sync-before-notify (Task 3), `.env.example`/compose/README (Task 4), manual curl + end-to-end (Task 5). Error-handling (log-and-never-raise) is covered by Task 2's swallow test and Task 3's suite-wide no-op behavior.
- No placeholders; every code step contains full code.
- Type consistency: `trigger_ldap_sync(config, send=None)` / `_send(url, api_key)` signatures are identical in Tasks 2 and 3; `Config.pocketid_url` / `pocketid_api_key` names match across Tasks 1-3; `make_config` (conftest) accepts the new fields as dataclass kwargs automatically since Task 1 adds defaulted fields.
