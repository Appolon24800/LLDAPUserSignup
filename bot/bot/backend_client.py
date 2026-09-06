"""HTTP client for the backend's internal API (shared-secret authenticated)."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import httpx


class BackendError(Exception):
    """Raised when the backend answers with an error or is unreachable."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class BackendClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-Internal-API-Key": self.api_key},
            timeout=self.timeout,
            transport=self.transport,
        )

    async def _request(self, method: str, path: str, json: dict | None = None) -> Any:
        try:
            async with self._client() as client:
                res = await client.request(method, path, json=json)
        except httpx.HTTPError as err:
            raise BackendError(f"backend unreachable: {err}") from err
        if res.status_code == 401:
            raise BackendError("backend rejected the internal API key", 401)
        if res.status_code >= 400:
            detail = ""
            with suppress(Exception):
                detail = res.json().get("error", {}).get("message", "")
            raise BackendError(detail or f"backend error ({res.status_code})", res.status_code)
        if res.status_code == 204 or not res.content:
            return None
        return res.json()

    async def create_code(self, groups: list[str], created_by: str) -> dict:
        return await self._request(
            "POST", "/internal/codes", json={"groups": groups, "created_by": created_by}
        )

    async def list_codes(self) -> list[dict]:
        return (await self._request("GET", "/internal/codes")).get("codes", [])

    async def revoke_code(self, code: str) -> bool:
        return (await self._request("POST", "/internal/revoke", json={"code": code})).get(
            "revoked", False
        )

    async def list_groups(self) -> list[dict]:
        """[{name, members}] ordered most-members-first (server-side order)."""
        return (await self._request("GET", "/internal/groups")).get("groups", [])
