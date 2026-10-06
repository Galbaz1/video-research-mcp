"""Identity-bearing comment samples and fixed deterministic audience cohorts."""

from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, Field, model_validator

from .collections import Scope
from .corpus import ID, CorpusModel, Digest


def timestamp(value: str) -> str:
    """Validate an aware ISO timestamp while preserving its exact supplied spelling."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamp must include an explicit UTC offset")
    return value


Timestamp = Annotated[str, Field(min_length=1, max_length=64), AfterValidator(timestamp)]


class Comment(CorpusModel):
    """An exact supplied quote; replies retain both their own and parent identities."""

    video_id: ID
    comment_id: ID
    thread_id: ID
    parent_comment_id: ID | None = None
    reply_id: ID | None = None
    posted_at: Timestamp
    quoted_text: str = Field(min_length=1, max_length=8000)
    author: str | None = Field(default=None, max_length=256)
    like_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def reply_identity(self):
        """Refuse ambiguous reply identities without requiring a complete sampled thread."""
        if self.parent_comment_id is None:
            if self.reply_id is not None:
                raise ValueError("A reply requires its parent_comment_id")
        elif self.reply_id != self.comment_id or self.parent_comment_id == self.comment_id:
            raise ValueError("A reply_id must equal comment_id and name a different parent")
        return self


class Video(CorpusModel):
    """Caller-supplied metadata compatible with existing YouTube metadata fields."""

    video_id: ID
    channel_id: ID
    title: str = Field(min_length=1, max_length=500)
    tags: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(default_factory=list, max_length=50)
    published_at: Timestamp
    duration_seconds: float = Field(ge=0, le=86400)
    format: Literal["short", "long"]
    view_count: int | None = Field(default=None, ge=0)
    like_count: int | None = Field(default=None, ge=0)
    comment_count: int | None = Field(default=None, ge=0)
    opening_text: str | None = Field(default=None, min_length=1, max_length=1000)


class Sample(CorpusModel):
    """Immutable sampled comments and metadata, with no claim of platform completeness."""

    sample_id: ID
    source_revision: ID
    source: Literal["youtube", "caller_fixture"]
    source_url: str = Field(min_length=1, max_length=2048)
    retrieved_at: Timestamp
    sampling_method: str = Field(min_length=1, max_length=256)
    sample_size: int = Field(ge=0, le=500)
    population_size: int | None = Field(default=None, ge=0)
    comments: list[Comment] = Field(max_length=500)
    videos: list[Video] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def exact_sample(self):
        """Reject duplicate identities and mismatched denominators before any database write."""
        if self.sample_size != len(self.comments):
            raise ValueError("sample_size must equal the number of supplied exact comments")
        if self.population_size is not None and self.population_size < self.sample_size:
            raise ValueError("population_size cannot be smaller than sample_size")
        keys = [(c.video_id, c.comment_id) for c in self.comments]
        if len(set(keys)) != len(keys) or len({v.video_id for v in self.videos}) != len(self.videos):
            raise ValueError("Duplicate comment or metadata video identity")
        return self


class AudienceScope(Scope):
    """Explicit existing collection; workspace context is not an authentication boundary."""

    collection: ID


class Import(AudienceScope):
    """Admit one immutable sample with the shared optimistic collection revision."""

    action: Literal["import"]
    expected_revision: int = Field(ge=1)
    sample: Sample


class Search(AudienceScope):
    """Literal casefolded search of caller-selected immutable samples with finite output."""

    action: Literal["search"]
    sample_ids: list[ID] = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=256)
    offset: int = Field(default=0, ge=0, le=5000)
    limit: int = Field(default=20, ge=1, le=50)
    output_bytes: int = Field(default=65536, ge=2048, le=65536)


class Analyze(AudienceScope):
    """Freeze a supplied video cohort and IANA timezone for transparent local metrics."""

    action: Literal["analyze"]
    sample_id: ID
    video_ids: list[ID] = Field(min_length=1, max_length=100)
    timezone: str = Field(min_length=1, max_length=128)
    evidence_limit: int = Field(default=5, ge=1, le=20)
    output_bytes: int = Field(default=65536, ge=2048, le=65536)

    @model_validator(mode="after")
    def fixed_cohort(self):
        """Require a real named timezone and a unique explicit cohort."""
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unknown IANA timezone") from error
        if len(set(self.video_ids)) != len(self.video_ids):
            raise ValueError("Duplicate cohort video identity")
        return self


Request = Annotated[Import | Search | Analyze, Field(discriminator="action")]


class Response(CorpusModel):
    """Local receipts keep provenance, evidence and sample-based limitations inspectable."""

    status: Literal["imported", "unchanged", "found", "no_evidence", "analyzed"]
    workspace: ID
    collection: ID
    index_revision: int
    sample_id: ID | None = None
    sample_sha256: Digest | None = None
    sampling: dict = Field(default_factory=dict)
    records: list[dict] = Field(default_factory=list)
    next_offset: int | None = None
    total_matches: int = 0
    analysis: dict = Field(default_factory=dict)
    provider_calls: Literal[0] = 0
    model_calls: Literal[0] = 0
