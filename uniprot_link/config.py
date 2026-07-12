"""Configuration management for uniprot-link.

Settings load from environment variables with the ``UNIPROT_LINK_`` prefix
(nested models use ``__``, e.g. ``UNIPROT_LINK_SPARQL__TIMEOUT=45``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from uniprot_link import __version__


class SparqlEndpointConfig(BaseModel):
    """UniProt SPARQL endpoint configuration."""

    base_url: str = Field(
        default="https://sparql.uniprot.org/sparql",
        description="UniProt SPARQL endpoint URL.",
    )
    contact_email: str = Field(
        default="bernt.popp@charite.de",
        description=(
            "Contact email embedded in the User-Agent. UniProt asks programmatic "
            "clients to provide one so they can reach you about problems."
        ),
    )
    timeout: int = Field(
        default=30,
        ge=1,
        le=600,
        description="Default per-request timeout in seconds (server hard limit is 45 min).",
    )
    rate_limit_per_second: float = Field(
        default=3.0,
        gt=0.0,
        le=20.0,
        description="Client-side request rate (requests per second).",
    )
    burst_size: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum burst size for the token-bucket rate limiter.",
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        le=6,
        description="Retry attempts for transient (429/5xx/network) failures.",
    )
    retry_delay: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Base delay (seconds) for exponential backoff between retries.",
    )
    default_limit: int = Field(
        default=50,
        ge=1,
        le=10000,
        description="LIMIT auto-injected into SELECT queries that lack one.",
    )
    max_limit: int = Field(
        default=10000,
        ge=1,
        le=100000,
        description="Hard cap on the LIMIT applied to any SELECT query.",
    )
    max_response_bytes: int = Field(
        # 32 MiB. Deliberately ABOVE the 8 MiB untrusted-text fence
        # (mcp.untrusted_content.DEFAULT_MAX_TOTAL_TEXT_BYTES) so it never rejects a
        # SELECT result the fence already permits; must stay above it.
        default=33_554_432,
        ge=1,
        le=268_435_456,
        description=(
            "Hard cap (bytes) on a streamed SPARQL response body; the request "
            "errors past it and NEVER truncates (a partial result set is "
            "unparseable). Keep this above the 8 MiB untrusted-text fence."
        ),
    )

    @property
    def user_agent(self) -> str:
        """User-Agent string with a contact mailbox, per UniProt etiquette."""
        return f"uniprot-link/{__version__} (mailto:{self.contact_email})"

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        """Normalise the endpoint URL (no trailing slash)."""
        return v.rstrip("/")


class CacheConfigModel(BaseModel):
    """In-process query cache configuration."""

    size: int = Field(default=512, ge=0, le=10000, description="Max cached query results.")
    ttl: int = Field(default=3600, ge=0, le=86400, description="Cache TTL in seconds.")


class ServerSettings(BaseSettings):
    """Top-level server settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="UNIPROT_LINK_",
        env_nested_delimiter="__",
    )

    host: str = Field(default="127.0.0.1", description="Server host.")
    port: int = Field(default=8000, ge=1024, le=65535, description="Server port.")
    reload: bool = Field(default=False, description="Enable auto-reload in development.")

    transport: Literal["unified", "http"] = Field(
        default="unified",
        description="Server transport mode (Streamable HTTP only).",
    )
    mcp_path: str = Field(default="/mcp", description="MCP endpoint path.")
    allowed_hosts: list[str] = Field(
        default=["localhost", "127.0.0.1", "::1"],
        description="Exact Host header values accepted by the request guard.",
    )
    allowed_origins: list[str] = Field(
        default=[],
        description="Browser Origin values accepted by the request guard.",
    )

    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins.",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level.",
    )
    log_format: Literal["json", "console"] = Field(
        default="console",
        description="Log format.",
    )

    sparql: SparqlEndpointConfig = Field(
        default_factory=SparqlEndpointConfig,
        description="UniProt SPARQL endpoint configuration.",
    )
    cache: CacheConfigModel = Field(
        default_factory=CacheConfigModel,
        description="Query cache configuration.",
    )

    @field_validator("mcp_path")
    @classmethod
    def validate_mcp_path(cls, v: str) -> str:
        """Ensure the MCP path starts with a forward slash."""
        return v if v.startswith("/") else f"/{v}"

    @field_validator("allowed_hosts", "allowed_origins", "cors_origins", mode="before")
    @classmethod
    def parse_string_list(cls, v: Any) -> list[str]:
        """Parse string lists from a comma-separated value or list."""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return list(v) if v else []

    @field_validator("allowed_hosts")
    @classmethod
    def reject_wildcard_host(cls, v: list[str]) -> list[str]:
        """Require exact hosts; pattern syntax makes the boundary ambiguous."""
        if any(any(marker in host for marker in "*?[]") for host in v):
            raise ValueError("wildcard patterns are not allowed in allowed_hosts")
        return v


settings = ServerSettings()
