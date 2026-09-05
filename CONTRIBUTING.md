# Contributing

## Ground rules

- `main` must always build, pass lint, and pass tests. Never push WIP or red commits.
- Write or update tests in the same commit as the feature/fix they cover, where practical.
- Security-relevant changes (auth, rate limiting, validation, image handling) must
  come with tests covering the new behavior — including the failure paths.

## Commits

Small, single-purpose commits with conventional-commit subjects:

```
feat(backend): add code revocation endpoint
fix(bot): clamp picker pagination at bounds
test(frontend): cover password mismatch feedback
build: bump python base image
ci: add pip-audit to PR gate
docs: document PROXY_TRUSTED_COUNT
chore: tidy fixtures
```

Scope is the component (`backend`, `bot`, `frontend`, or omitted for repo-wide changes).

## Before you push

Run the same gates CI runs:

```sh
cd backend && ruff check . && pytest
cd bot    && ruff check . && pytest
cd frontend && npm ci && npm run lint && npm test && npm run build
```

## Adding a translation key

1. Add the key to `frontend/src/i18n/en.json` and `fr.json` (both, always).
2. Use it via `t("...")`; never hardcode user-facing strings.
3. Server error codes map to `errors.<code>` keys — when adding a backend error
   code, add the matching translation entries in the same commit.
