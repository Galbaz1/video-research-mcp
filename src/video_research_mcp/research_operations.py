"""Durable research operation submission, reconciliation and retained report readback."""

from __future__ import annotations

from contextlib import nullcontext
from uuid import uuid4

from .client import GeminiClient
from .config import get_config
from .errors import make_tool_error
from .job_store import JobStore
from .redaction import redact_text
from .research_jobs import (
    TERMINAL,
    find_operation,
    live_lease,
    prepare_launch,
    record_status,
    retained_result,
    receipt,
)
from .models.research_web import DeepResearchFollowup, DeepResearchLaunch
from .tools.research_web import _extract_report
from .research_poll import retrieve as _retrieve, report as _report


async def _submit(store, job, owner, payload):
    """Submit once under a live lease; lost response/cancellation remains unknown."""
    try:
        async with live_lease(store, job["job_id"], owner):
            return await GeminiClient.get().aio.interactions.create(**payload)
    except BaseException as exc:
        store.checkpoint(
            job["job_id"], owner, status="unknown", error=redact_text(str(exc)), release=True
        )
        raise


async def launch(topic: str, output_format: str, job_id: str | None) -> dict:
    """Execute the durable launch operation and retain exact controller state."""
    job = None
    try:
        prompt = topic
        if output_format:
            prompt = f"{topic}\n\nOutput format:\n{output_format}"

        cfg = get_config()

        payload = {
            "input": prompt,
            "agent": cfg.deep_research_agent,
            "background": True,
            "store": True,
        }
        job, owner = prepare_launch(
            "research_web",
            {"topic": topic, "output_format": output_format, **payload},
            job_id,
        )
        if not owner:
            return retained_result(job)
        store = JobStore()
        interaction = await _submit(store, job, owner, payload)
        if interaction.status == "completed":
            result = _report(interaction.id, interaction, job)
        else:
            result = DeepResearchLaunch(
                interaction_id=interaction.id,
                status=getattr(interaction, "status", "unknown") or "unknown",
            ).model_dump(mode="json")
        return record_status(store, job, owner, result)

    except Exception as exc:
        result = make_tool_error(exc)
        if job:
            result["job_receipt"] = receipt(JobStore().get(job["job_id"]))
        return result


async def poll(interaction_id: str) -> dict:
    """Execute the durable poll operation and retain exact controller state."""
    job = None
    owner = ""
    try:
        store = JobStore()
        job = find_operation(interaction_id)
        if job and job["status"] in TERMINAL:
            return retained_result(job)
        owner = uuid4().hex
        if job and store.claim(job["job_id"], owner) is None:
            return retained_result(job)
        async with live_lease(store, job["job_id"], owner) if job else nullcontext():
            interaction = await _retrieve(interaction_id)
        result = _report(interaction_id, interaction, job)
        if result["status"] != "completed":
            return record_status(store, job, owner, result) if job else result

        if job:
            result = record_status(store, job, owner, result)

        from .weaviate_store import store_deep_research, extract_and_store_graph

        await store_deep_research(result)
        await extract_and_store_graph(
            result,
            result.get("topic") or interaction_id,
            source_tool="research_web",
            source_category="research",
        )

        return result

    except Exception as exc:
        if job and owner:
            store.checkpoint(job["job_id"], owner, error=redact_text(str(exc)), release=True)
        return make_tool_error(exc)


async def followup(interaction_id: str, question: str, job_id: str | None) -> dict:
    """Execute the durable followup operation and retain exact controller state."""
    job = None
    try:
        cfg = get_config()

        payload = {
            "previous_interaction_id": interaction_id,
            "input": question,
            "model": cfg.default_model,
            "generation_config": {"thinking_level": cfg.default_thinking_level},
        }
        job, owner = prepare_launch("research_followup", payload, job_id)
        if not owner:
            return retained_result(job)
        store = JobStore()
        followup = await _submit(store, job, owner, payload)
        if followup.status != "completed":
            return record_status(
                store, job, owner, {"interaction_id": followup.id, "status": followup.status}
            )
        response_text, _ = _extract_report(followup)
        result = DeepResearchFollowup(
            interaction_id=followup.id,
            previous_interaction_id=interaction_id,
            response=response_text.strip(),
        ).model_dump(mode="json")
        result["status"] = "completed"
        result = record_status(store, job, owner, result)

        from .weaviate_store import store_deep_research_followup

        await store_deep_research_followup(
            interaction_id,
            followup.id,
            question=question,
            response=response_text.strip(),
        )

        return result

    except Exception as exc:
        result = make_tool_error(exc)
        if job:
            result["job_receipt"] = receipt(JobStore().get(job["job_id"]))
        return result


async def cancel(interaction_id: str) -> dict:
    """Execute the durable cancel operation and retain exact controller state."""
    job = None
    owner = ""
    try:
        store = JobStore()
        job = find_operation(interaction_id)
        if job and job["status"] in TERMINAL:
            return retained_result(job)
        if job:
            store.cancel(job["job_id"])
            owner = uuid4().hex
            if store.claim(job["job_id"], owner) is None:
                return retained_result(store.get(job["job_id"]))
        client = GeminiClient.get()
        response = await client.aio.interactions.cancel(interaction_id)
        if response is not None and response.id != interaction_id:
            raise ValueError("Provider returned a different cancellation interaction ID")
        result = {
            "interaction_id": interaction_id,
            "status": getattr(response, "status", "cancel_requested") or "cancel_requested",
        }
        return record_status(store, job, owner, result) if job else result

    except Exception as exc:
        if job and owner:
            store.checkpoint(job["job_id"], owner, error=redact_text(str(exc)), release=True)
        return make_tool_error(exc)
