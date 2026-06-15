"""Unified server manager for HTTP and unified (HTTP+MCP) transports.

Streamable HTTP only: the MCP surface is served at ``/mcp`` alongside the FastAPI
host. There is no stdio transport.
"""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI
    from structlog.typing import FilteringBoundLogger


class UnifiedServerManager:
    """Orchestrate startup of uniprot-link in any transport mode."""

    def __init__(self, logger: FilteringBoundLogger | None = None) -> None:
        """Build a manager with an optional structlog logger."""
        self.logger = logger
        self._uvicorn_server: uvicorn.Server | None = None

    async def start_unified_server(self, host: str, port: int) -> None:
        """Start FastAPI + MCP (streamable-http) on the same port."""
        if self.logger:
            self.logger.info("Starting unified server", host=host, port=port, mcp_path="/mcp")

        from uniprot_link.app import app as fastapi_app
        from uniprot_link.config import settings
        from uniprot_link.mcp.facade import create_uniprot_mcp

        mcp = create_uniprot_mcp()
        mcp_asgi = mcp.http_app(path=settings.mcp_path)

        original_lifespan = fastapi_app.router.lifespan_context

        @asynccontextmanager
        async def combined_lifespan(app: FastAPI) -> AsyncIterator[None]:
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(original_lifespan(app))
                await stack.enter_async_context(mcp_asgi.router.lifespan_context(app))
                yield

        fastapi_app.router.lifespan_context = combined_lifespan
        fastapi_app.mount("/", mcp_asgi)

        config = uvicorn.Config(
            app=fastapi_app, host=host, port=port, log_config=None, lifespan="on"
        )
        self._uvicorn_server = uvicorn.Server(config)
        await self._uvicorn_server.serve()

    async def start_http_only_server(self, host: str, port: int) -> None:
        """Start FastAPI only (no MCP)."""
        if self.logger:
            self.logger.info("Starting HTTP-only server", host=host, port=port)
        from uniprot_link.app import app as fastapi_app

        config = uvicorn.Config(
            app=fastapi_app, host=host, port=port, log_config=None, lifespan="on"
        )
        self._uvicorn_server = uvicorn.Server(config)
        await self._uvicorn_server.serve()

    async def shutdown(self) -> None:
        """Gracefully stop any running server."""
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
        if self.logger:
            self.logger.info("Shutdown complete")
