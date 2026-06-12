"""FastAPI host for uniprot-link (thin: health + service info)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from uniprot_link import __version__
from uniprot_link.config import settings
from uniprot_link.logging_config import configure_logging
from uniprot_link.services.constants import UNIPROT_RELEASE

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: configure logging on startup."""
    logger = configure_logging()
    logger.info("uniprot-link starting", host=settings.host, port=settings.port)
    yield
    logger.info("uniprot-link shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="uniprot-link",
        description="MCP/API server grounding protein research in the UniProt SPARQL endpoint.",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Liveness probe."""
        return {"status": "ok", "service": "uniprot-link", "version": __version__}

    @app.get("/")
    async def root() -> dict[str, Any]:
        """Service information."""
        return {
            "name": "uniprot-link",
            "version": __version__,
            "uniprot_release": UNIPROT_RELEASE,
            "endpoint": settings.sparql.base_url,
            "mcp_endpoint": settings.mcp_path,
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = create_app()
