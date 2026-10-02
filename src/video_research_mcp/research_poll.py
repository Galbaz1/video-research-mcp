"""Bounded provider readback and typed report extraction without launching work."""

import asyncio
import logging
import time

from .client import GeminiClient
from .models.research_web import DeepResearchResult
from .tools.research_web import _extract_report, _extract_usage

logger = logging.getLogger(__name__)


async def retrieve(interaction_id: str):
    """Read provider status with at most three requests for transient 403 responses."""
    client = GeminiClient.get()
    for attempt in range(3):
        try:
            interaction = await client.aio.interactions.get(interaction_id)
            if interaction.id != interaction_id:
                raise ValueError("Provider returned a different interaction ID")
            return interaction
        except Exception as exc:
            if "403" not in str(exc).lower() or attempt == 2:
                raise
            logger.warning("Transient 403 on status poll (attempt %d/3)", attempt + 1)
            await asyncio.sleep(5 * (attempt + 1))


def report(interaction_id: str, interaction, job: dict | None) -> dict:
    """Preserve terminal errors and bind report metadata to retained launch evidence."""
    status = getattr(interaction, "status", "unknown") or "unknown"
    if status != "completed":
        result = {"interaction_id": interaction_id, "status": status}
        if interaction.errors:
            result["errors"] = [error.model_dump(mode="json") for error in interaction.errors]
        return result
    report_text, sources = _extract_report(interaction)
    return DeepResearchResult(
        interaction_id=interaction_id,
        status="completed",
        topic=job["request"].get("topic", "") if job else "",
        report_text=report_text,
        sources=sources,
        source_count=len(sources),
        duration_seconds=int(time.time() - job["created_at"]) if job else None,
        usage=_extract_usage(interaction),
    ).model_dump(mode="json")
