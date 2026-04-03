"""Async client for querying a Grist document via its SQL endpoint."""

import httpx


class GristClient:
    """Thin async client — executes parameterized SQL against Grist."""

    def __init__(self, api_url: str, api_key: str, doc_id: str) -> None:
        self.sql_url = f"{api_url}/api/docs/{doc_id}/sql"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(headers=self._headers, timeout=10)

    async def execute(self, sql: str, args: list) -> list[dict]:
        """
        Run a parameterized SQL query and return result rows.

        Grist's SQL endpoint accepts {"sql": "...", "args": [...]} and returns
        {"records": [{"fields": {...}}, ...]}.

        Only parameterized queries are accepted — never interpolate user input
        into the SQL string (see THREAT_MODEL.md T4).
        """
        if self._client is None:
            await self.connect()
        resp = await self._client.post(
            self.sql_url,
            json={"sql": sql, "args": args},
        )
        resp.raise_for_status()
        return [r["fields"] for r in resp.json().get("records", [])]

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
