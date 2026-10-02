"""Explicit session scope and local, non-authoritative memory operations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SessionScope(BaseModel):
    """Caller-selected workspace and notebook, compared exactly without fallback."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace_id: str = Field(min_length=1, max_length=256, pattern=r"\S")
    notebook_id: str = Field(min_length=1, max_length=256, pattern=r"\S")


class SessionMemoryRequest(BaseModel):
    """Inspect bounded history or explicitly read/edit/delete one derived profile."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["get", "set", "delete", "history", "list", "search", "compact"]
    scope: SessionScope | None = None
    source_id: str = Field(min_length=1, max_length=256)
    session_id: str = Field(min_length=1, max_length=128)
    synopsis: str | None = Field(default=None, max_length=32768)
    expected_revision: int = Field(default=0, ge=0)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=100)
    pattern: str = Field(default="messages/*", min_length=1, max_length=256)
    query: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def operation_fields(self):
        """Require current-operation inputs instead of inferring identity or authority."""
        if self.action in {"get", "set", "delete"} and self.scope is None:
            raise ValueError("Derived memory requires explicit workspace/notebook scope")
        if self.action == "set" and self.synopsis is None:
            raise ValueError("Memory edits require synopsis text")
        if self.action != "set" and self.synopsis is not None:
            raise ValueError("Synopsis text is only accepted by a memory edit")
        if (self.action == "search") != (self.query is not None):
            raise ValueError("A literal query is required only for original-text search")
        return self


class SessionMemoryResponse(BaseModel):
    """Local data response; conversation and learned text are never verified media evidence."""

    status: str
    scope: SessionScope | None
    source_id: str
    memory: dict | None = None
    history: dict | None = None
    selection: dict | None = None
    authoritative: bool = False
    source_verified: bool = False
    source_data_is_instruction: bool = False
