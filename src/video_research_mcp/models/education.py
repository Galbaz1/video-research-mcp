"""Strict source, analysis, script and storyboard for one finite three-domain lesson."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .image_edit import Number, StrictModel

Text = Annotated[str, Field(min_length=1, max_length=8192)]
Point = tuple[Number, Number]


class LessonSource(StrictModel):
    """The caller's problem and authority assertion, independently hash-bound as source data."""

    problem: Text
    authority: Text


class LessonAnalysis(StrictModel):
    """Concrete required rules; numeric domain checks do not trust an asserted passed flag."""

    triangle_rule: Literal["AB perpendicular BC; AB=4,BC=3,AC=5"]
    curve_rule: Literal["square_input_reflection"]
    circuit_rule: Literal["one_series_cycle"]


class LessonCaption(StrictModel):
    """Caller-declared transcript timing, separately admitted against measured supplied audio."""

    scene_id: Literal["triangle", "curve", "circuit"]
    start_seconds: Annotated[Number, Field(ge=0, le=6)]
    end_seconds: Annotated[Number, Field(gt=0, le=6)]
    text: Annotated[str, Field(min_length=1, max_length=76)]


class LessonScript(StrictModel):
    """Preserved verbatim transcript plus three displayed caption intervals."""

    transcript: Text
    captions: Annotated[list[LessonCaption], Field(min_length=3, max_length=3)]


class GeometryScene(StrictModel):
    """Numeric vertices supply both domain predicates and the displayed triangle."""

    id: Literal["triangle"]
    kind: Literal["geometry"]
    start_seconds: Number
    end_seconds: Number
    equation: Text
    points: dict[str, Point]


class CurveScene(StrictModel):
    """Explicit square samples must agree with the reflected input expression."""

    id: Literal["curve"]
    kind: Literal["curve"]
    start_seconds: Number
    end_seconds: Number
    equation: Text
    function: Literal["square"]
    input_reflection: Annotated[bool, Field(strict=True)]
    shift: Number
    samples: Annotated[list[Point], Field(min_length=33, max_length=33)]


class CircuitScene(StrictModel):
    """Exact named terminals and unique wiring define the closed two-component cycle."""

    id: Literal["circuit"]
    kind: Literal["circuit"]
    start_seconds: Number
    end_seconds: Number
    equation: Text
    components: Annotated[list[Literal["battery", "resistor"]], Field(min_length=2, max_length=2)]
    terminals: dict[str, Point]
    wires: Annotated[list[tuple[str, str]], Field(min_length=2, max_length=2)]


Scene = Annotated[GeometryScene | CurveScene | CircuitScene, Field(discriminator="kind")]


class LessonStoryboard(StrictModel):
    """An exact required scene population, rather than optional or skipped domain checks."""

    scenes: Annotated[list[Scene], Field(min_length=3, max_length=3)]


class LessonSpec(StrictModel):
    """Bounded first-party family without an arbitrary expression or foreign template route."""

    schema_version: Literal[1]
    title: Literal["Verifying a diagram against its rule"]
    source: LessonSource
    analysis: LessonAnalysis
    script: LessonScript
    storyboard: LessonStoryboard

    @model_validator(mode="before")
    @classmethod
    def exact_version(cls, value):
        """Reject boolean/nonnumeric protocol versions before literal coercion."""
        if isinstance(value, dict) and type(value.get("schema_version")) is not int:
            raise ValueError("Lesson schema_version must be the integer1")
        return value
