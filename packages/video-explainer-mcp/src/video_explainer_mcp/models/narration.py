"""Explicit requests for companion-owned measured WAV production."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NarrationRequest(BaseModel):
    """Select a performance without changing its approved original transcript."""

    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["generate", "preview", "custom"] = "generate"
    provider: Literal["mock", "qwen", "minimax"] = "mock"
    voice: str = Field(default="tone", min_length=1, max_length=128)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    language: str = Field(default="English", min_length=1, max_length=32)
    region: Literal["global", "cn"] = "global"
    rate: float = Field(default=1.0, ge=0.5, le=2.0, allow_inf_nan=False)
    pause_seconds: float = Field(default=0.1, ge=0, le=2.0, allow_inf_nan=False)
    scene_id: str | int | None = None
    custom_audio: str | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def selected_route(self):
        """Reject missing models and action fields that cannot be honored."""
        if self.provider == "mock":
            if self.voice != "tone" or self.model not in (None, "tone-v1"):
                raise ValueError("Mock narration supports only tone / tone-v1")
            self.model = "tone-v1"
        elif self.model is None:
            raise ValueError("Real narration requires an explicit supported model")
        if self.scene_id is not None and self.action != "preview":
            raise ValueError("scene_id is only available for preview")
        if (self.custom_audio is not None) != (self.action == "custom"):
            raise ValueError("custom requires custom_audio; other actions cannot select it")
        if self.action == "custom" and self.rate != 1:
            raise ValueError("Custom WAV rate changes require a separately qualified processor")
        return self
