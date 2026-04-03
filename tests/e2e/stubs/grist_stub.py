"""In-process Grist HTTP stub server.

Starts an aiohttp server on a random port that mimics the Grist SQL endpoint.
Test code registers canned responses keyed by SQL string; the stub captures
every query it receives so tests can assert on the exact SQL + args sent.
"""

from dataclasses import dataclass, field

from aiohttp import web


@dataclass
class CapturedQuery:
    sql: str
    args: list


class GristStub:
    """Fake Grist SQL endpoint for E2E tests."""

    def __init__(self) -> None:
        self.port: int | None = None
        self.captured_queries: list[CapturedQuery] = []
        self._canned: dict[str, list[dict]] = {}
        self._error_sqls: set[str] = set()
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None

    # -- configuration helpers (call before starting) --

    def set_response(self, sql: str, rows: list[dict]) -> None:
        """Register a canned response for a given SQL string."""
        self._canned[sql] = rows

    def set_error(self, sql: str) -> None:
        """Make the stub return HTTP 500 for a given SQL string."""
        self._error_sqls.add(sql)

    # -- lifecycle --

    async def start(self) -> None:
        self._app = web.Application()
        self._app.router.add_post("/api/docs/{doc_id}/sql", self._handle_sql)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        # Extract the port the OS assigned
        self.port = site._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # -- request handler --

    async def _handle_sql(self, request: web.Request) -> web.Response:
        body = await request.json()
        sql = body.get("sql", "")
        args = body.get("args", [])
        self.captured_queries.append(CapturedQuery(sql=sql, args=args))

        if sql in self._error_sqls:
            return web.Response(status=500, text="Internal Server Error")

        rows = self._canned.get(sql, [])
        records = [{"fields": row} for row in rows]
        return web.json_response({"records": records})
