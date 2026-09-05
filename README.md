# LLDAP User Signup

Self-service user registration for an existing [LLDAP](https://github.com/lldap/lldap) server.

Three components:

- **backend/** — Flask + ldap3 + SQLite: registration codes, rate limiting, user creation.
- **bot/** — Telegram admin bot: generates single-use, group-scoped registration links.
- **frontend/** — React (TypeScript) registration wizard, black-and-white, English/French.

> Full setup documentation is added as the project develops. Quick start:
> `cp .env.example .env`, fill it in, then `docker compose up -d`.
