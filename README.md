# LLDAP User Signup

Self-service user registration for an existing [LLDAP](https://github.com/lldap/lldap) server.

An admin generates a single-use, group-scoped invitation link with a Telegram bot;
the new user opens the link and completes a simple, mobile-friendly wizard; the
backend creates the LLDAP user (with an optional re-encoded profile photo) and
adds them to the invited groups.

```
┌──────────┐  /gen,/list,/revoke   ┌──────────┐   ldap3 (LDAPS/StartTLS)   ┌────────┐
│ Telegram  │ ───────────────────▶ │  Backend │ ─────────────────────────▶ │  LLDAP │
│   Bot     │   internal API +     │  Flask   │                            │(already│
└──────────┘   shared secret       │  SQLite  │                            │running)│
                                   └────▲─────┘                            └────────┘
        {BASE_URL}/register?code=…         │ /api/v1 (JSON)
┌──────────┐  HTTPS (your reverse proxy)   │
│  React   │ ──────────────────────────────┘
│ Frontend │   (same-origin via bundled nginx)
└──────────┘
```

## Quick start

Requirements: Docker + docker compose, an existing LLDAP instance, a Telegram bot token.

1. **Create the bot**: message [@BotFather](https://t.me/BotFather), `/newbot`, copy the token.
2. **Find your Telegram user ID**: message [@userinfobot](https://t.me/userinfobot).
3. **Configure**:

   ```sh
   cp .env.example .env
   # Fill in every value; generate the two secrets with:
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

4. **Run**:

   ```sh
   docker compose up -d
   ```

5. In Telegram, send `/gen` to your bot, pick groups, confirm — you get a link
   like `https://signup.example.com/register?code=<token>` to forward to the new user.

Images are also published on every push to `main` and on `v*` tags:
`ghcr.io/appolon24800/lldapusersignup-{backend,bot,frontend}` (tags: `latest`,
git SHA, semver). The compose file builds locally by default; swap `build:` for
`image:` if you prefer the registry images.

## TLS termination (required in production)

Neither Flask/gunicorn nor the bundled nginx terminate TLS. Put your usual
reverse proxy in front of the published frontend port and forward `X-Forwarded-For`:

**Caddy** (`Caddyfile`):

```
signup.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

**nginx**:

```nginx
server {
    listen 443 ssl http2;
    server_name signup.example.com;
    ssl_certificate     /etc/letsencrypt/live/signup.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/signup.example.com/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

There are now **two** proxy hops in front of the backend (your proxy + the bundled
nginx), so set `PROXY_TRUSTED_COUNT=2` in `.env` — this keeps IP-based rate
limiting and lockouts keyed on the real client address.

## Telegram bot commands

| Command | Effect |
|---|---|
| `/gen [group1,group2]` | Create a registration code. Without arguments opens a paginated group picker (ordered by membership count, most-used first, with the count shown per group). The reply contains the full, copyable link. |
| `/list` | Active (unused, unexpired) codes with hint, groups and expiry. |
| `/revoke <code>` | Invalidate a code immediately. |
| `/start`, `/help` | Usage text. |

Only `TELEGRAM_ADMIN_IDS` may use commands; everyone else gets a generic
"not authorized" reply. Each user is throttled to 30 commands/minute.

**Registration notifications**: when `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_ADMIN_IDS` reach the backend too (compose passes them), every
successful registration sends `✅ <PLATFORM_NAME> account created: <display
name>` to the admin chats. Set `PLATFORM_NAME` to brand both that message
and the user-facing success screen ("<Platform> account created"). Sends
are fire-and-forget — a Telegram outage never affects signups.

## Security model

- **Codes**: 256-bit `secrets.token_urlsafe` values; only their SHA-256 hash is
  stored. Single-use with an atomic claim (no double-use race), optionally
  time-limited (`CODE_EXPIRY_MINUTES`, default 0 = no expiry), invalidated
  immediately on use, revoke, or `MAX_FAILED_ATTEMPTS` failed submissions.
- **Brute force**: per-IP exponential lockout shared across workers
  (SQLite-backed: 3 consecutive failures → 30 s, doubling, capped at 1 h), on
  top of Flask-Limiter request throttling (`RATE_LIMIT_VALIDATE`,
  `RATE_LIMIT_SUBMIT`). Successful validation resets the IP counter.
- **Validation** (server-side, always, client is never trusted): usernames
  `^[a-z0-9._-]{3,32}$` + reserved-name denylist + LDAP uniqueness; password
  ≥10 chars and ≥60 bits of pool-based entropy over unique characters, with a
  common-password denylist; names are unicode letters/spaces/hyphens/apostrophes.
- **Photos**: size-capped (`MAX_UPLOAD_MB`, default 2 MB), identified by magic
  bytes (never extensions), decoded with `verify()`, re-encoded server-side to
  JPEG ≤512×512 — EXIF/GPS metadata is stripped by the re-encode. The client's
  conversion is never trusted.
- **LDAP**: LDAPS or StartTLS before bind (credentials never cross the network
  in plaintext; plain LDAP requires explicit `LDAP_ALLOW_INSECURE=true` for
  development), certificate validation on by default.
- **Secrets**: backend env vars only — never in the frontend bundle, never in
  logs. The bot authenticates to the backend's `/internal/*` API with
  `INTERNAL_API_KEY` compared in constant time. CORS is locked to explicit
  origins (no wildcard allowed).
- **Containers**: multi-stage builds, dedicated non-root users, no unused
  packages, healthchecks on backend and frontend.

Failure semantics worth knowing: if LDAP fails after a code was claimed, the
claim is reverted and a half-created user is removed, so a server hiccup never
burns an invitation. A user retrying with a *taken* username does count toward
the code's failed attempts (5 by default) — the frontend checks most issues
before submission, and an admin can always `/gen` a fresh code.

## Development

```sh
# Backend (Python 3.12)
cd backend && pip install -r requirements-dev.txt
ruff check . && pytest

# Bot
cd bot && pip install -r requirements-dev.txt
ruff check . && pytest

# Frontend (Node 22)
cd frontend && npm ci
npm run lint && npm test && npm run build
```

Integration tests against a real LLDAP container run in CI
(`tests/integration/`); they skip locally unless `INTEGRATION_LLDAP_URL` is set.

## Repository layout

```
backend/   Flask app: validation, code store, lockouts, LDAP service, public + internal APIs
bot/       python-telegram-bot: admin commands, group picker, backend client
frontend/  Vite + React + TypeScript wizard, strict black-and-white design, EN/FR
docker-compose.yml, .env.example
.github/   CI (PR gate), release pipeline (GHCR), dependabot
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the commit and review conventions.
