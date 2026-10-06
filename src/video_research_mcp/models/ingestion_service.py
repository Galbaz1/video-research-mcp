"""Explicit operator-qualified loopback Docling service selection."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DoclingService(BaseModel):
    """Pin one deployment contract without importing its parser or model runtime."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    base_url: str = Field(min_length=1, max_length=2048)
    contract_route: Literal["/v1/capabilities"] = "/v1/capabilities"
    expected_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deployment_revision: str = Field(min_length=1, max_length=256)
    runtime_qualified: bool = False

    @model_validator(mode="after")
    def loopback_origin(self):
        """Keep uploaded source bytes on a literal selected loopback origin."""
        parsed = urlsplit(self.base_url)
        if (parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"127.0.0.1", "::1"}
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or any(ord(c) <= 32 or ord(c) == 127 for c in self.base_url)
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise ValueError("Docling requires a literal loopback origin without credentials or path")
        return self
