# Automatic PocketID LDAP sync after registration

Date: 2026-09-11
Status: approved design, pre-implementation

## Problem

PocketID (v2.x) uses LLDAP as its user source but only syncs LDAP on startup and
once per hour. A user created through this app's registration flow is therefore
invisible to PocketID — unable to log in via OIDC — until an admin clicks the
manual "sync LDAP" button in PocketID's admin UI. Today that refresh is manual.

## Goal

After a successful registration, trigger PocketID's LDAP sync automatically so
the new user can log in via PocketID within seconds, without an admin doing
anything and without ever coupling signup availability to PocketID.

## Verified PocketID facts

From the PocketID source (`pocket-id/pocket-id`, v2.x):

- `POST /api/application-configuration/sync-ldap` triggers a full LDAP sync
  inline and returns `204 No Content`.
- The endpoint is admin-only; the auth middleware accepts an API key via the
  `X-API-Key` header as an alternative to a session. Admin API keys are created
  in the PocketID admin UI at `/settings/admin/api-keys`.
- Absent a trigger, the scheduled sync (startup + hourly) is the fallback.

## Non-goals

- No retry/queueing of failed sync triggers — the hourly scheduled sync
  self-heals a missed trigger.
- No synchronous (awaited-in-request) sync — it would couple registration
  availability to PocketID.
- No support for other OIDC providers or a generic webhook — PocketID-specific,
  like `lldap_api.py` is LLDAP-specific.
- No PocketID container in CI; live verification is a manual curl step.

## Design

### Configuration

Two new optional environment variables, both-or-neither:

| Var | Meaning |
|---|---|
| `POCKETID_URL` | Base URL of the PocketID instance (e.g. `https://id.example.com`). Validated as an absolute http(s) URL when set — same rule as `REDIRECT_URL`. Trailing slash stripped. |
| `POCKETID_API_KEY` | Admin API key from PocketID's `/settings/admin/api-keys`. Required non-empty when `POCKETID_URL` is set. |

- Exactly one of the two set → `ConfigError` at startup ("fail fast on
  misconfiguration"; a half-configured sync would otherwise fail silently
  forever). Neither set → feature disabled, zero behavior change.
- New `Config` fields `pocketid_url: str = ""` and `pocketid_api_key: str = ""`.
- The API key is backend-env-only, handled like `LDAP_ADMIN_PASSWORD` (never in
  the frontend bundle, never logged).

### Module: `backend/app/pocketid.py`

Structural clone of `notifier.py` (stdlib only, thread-pool fire-and-forget):

- `trigger_ldap_sync(config, send=None) -> None`
  - No-op unless both `config.pocketid_url` and `config.pocketid_api_key` are
    set. Reads them off the config directly so the test seam stays a single
    injectable `send`.
  - `send` injectable for tests; production submits to a module-level
    `ThreadPoolExecutor(max_workers=1, thread_name_prefix="pocketid-sync")`.
- `_send(url: str, api_key: str) -> None`
  - `POST {url}/api/application-configuration/sync-ldap`, headers
    `{"X-API-Key": <key>}`, empty body, 10 s timeout, via `urllib.request`.
  - Any HTTP status outside 2xx (204 expected) or any exception →
    `logger.warning(...)` with context; never raises.

### Call site

`backend/app/api/public.py`, success block of the registration submit handler
(currently around the lockout reset / Telegram notification):

```python
_lockout().reset(request.remote_addr or "unknown")
trigger_ldap_sync(_cfg())                      # new — queued first
notify_account_created(_cfg(), display_name=full_name)
```

The sync is queued before the Telegram notification so it starts as early as
possible. Both are fire-and-forget: registration latency and success are
unaffected by PocketID's availability or speed.

### Failure semantics

Registration returns `201` regardless of the sync outcome. A failed trigger
logs a warning and is simply absent; PocketID's hourly scheduled sync imports
the user later regardless. This mirrors the repo's rule that a notification
integration must never affect signups.

### Testing

- New `backend/tests/test_pocketid.py`, mirroring `test_notifier.py`:
  - no-op when unconfigured (either field empty);
  - configured → `send` called once with the configured URL and API key;
  - `_send` turns HTTP errors / transport failures into logged non-raises
    (fake urlopen / post injection as in `test_lldap_api.py` style).
- `test_config.py`: `POCKETID_URL` URL validation; both-or-neither
  `ConfigError` cases; trailing-slash normalization.
- `test_api_public.py`: successful registration calls `trigger_ldap_sync`
  (patched, as `notify_account_created` already is).
- Manual verification step in the plan: one curl against the live instance —
  `curl -X POST -H "X-API-Key: ..." https://id.example.com/api/application-configuration/sync-ldap`
  expecting `204` — plus an end-to-end registration.

### Documentation

- `.env.example`: both vars with a comment noting the fallback behavior.
- `docker-compose.yml`: pass-through env entries for the backend service,
  mirroring the `TELEGRAM_*` handling.
- `README.md`: one sentence where registration notifications are described —
  an optional PocketID sync trigger, fire-and-forget, hourly sync as fallback.
