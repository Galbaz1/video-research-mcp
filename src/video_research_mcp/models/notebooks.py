"""Local notebook documents and requests over existing canonical corpus observations."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .collections import Scope
from .corpus import ID, CorpusModel, Digest


class Citation(CorpusModel):
    """One exact canonical observation version that supports a note."""

    collection: ID
    observation_id: ID
    source_revision: ID
    media_digest: Digest


class Note(CorpusModel):
    """Caller-written note text; support comes only from its cited observation passages."""

    note_id: ID
    revision: int = Field(ge=1, le=1000)
    text: str = Field(min_length=1, max_length=8000)
    citations: list[Citation] = Field(min_length=1, max_length=32)


class NotebookDocument(CorpusModel):
    """Portable notebook identity, revision, collection scope and notes; holds no secrets or provider state."""

    notebook_id: ID
    revision: int = Field(ge=1, le=10000)
    title: str = Field(min_length=1, max_length=256)
    collections: list[ID] = Field(min_length=1, max_length=32)
    notes: list[Note] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_scope(self):
        """Reject ambiguous collection scope, note identities and citations outside the scope."""
        if len(set(self.collections)) != len(self.collections):
            raise ValueError("Duplicate notebook collection")
        if len({note.note_id for note in self.notes}) != len(self.notes):
            raise ValueError("Duplicate note_id")
        if any(c.collection not in self.collections for note in self.notes for c in note.citations):
            raise ValueError("A citation names a collection outside this notebook")
        return self


class NotebookScope(Scope):
    """Explicit workspace and notebook; selection is not an authentication boundary."""

    notebook_id: ID


class Import(Scope):
    action: Literal["import"]
    document: NotebookDocument


class AddNote(NotebookScope):
    action: Literal["note"]
    expected_revision: int = Field(ge=1)
    note_id: ID
    text: str = Field(min_length=1, max_length=8000)
    citations: list[Citation] = Field(min_length=1, max_length=32)


class Query(NotebookScope):
    action: Literal["query"]
    query: str = Field(min_length=1, max_length=256)
    limit: int = Field(default=20, ge=1, le=50)


class Export(NotebookScope):
    action: Literal["export"]


class Status(Scope):
    action: Literal["status"]


Request = Annotated[Import | AddNote | Query | Export | Status, Field(discriminator="action")]


class Response(BaseModel):
    """Local receipts; external_services stays empty because no service is used."""

    model_config = ConfigDict(extra="allow")

    status: Literal["imported", "unchanged", "noted", "found", "no_evidence", "exported", "listed"]
    workspace: ID
    notebook_id: ID | None = None
    revision: int | None = None
    external_services: list[str] = Field(default_factory=list)
