"""Execute joined bounded research rounds and retain original-source packet artifacts."""

import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import quote, quote_plus
from uuid import uuid4

from .client import GeminiClient
from .config import get_config
from .evidence import validate_evidence_packet
from .job_execution import single_submission
from .media_snapshot import checked_path
from .models.evidence import EvidencePacket
from .models.research_execution import ResearchBranchAnswer, ResearchExecutionResponse
from .research_curate import curate
from .research_execution_provider import (ResearchBudget, ResearchBudgetFailure, check_sources,
                                         ResearchExecutionFailure, failure, prompt_for,
                                         protect, selected_account)
from .research_recovery import MAX_ARTIFACT_BYTES, record_result, replay
from .research_sources import prepare_sources


def write_state(path: Path, value: dict) -> str:
    """Publish only complete private JSON bytes, retaining the prior state on failure."""
    temporary = path.with_suffix(".pending")
    try:
        body = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
        if len(body) > MAX_ARTIFACT_BYTES:
            raise ResearchExecutionFailure("Research artifact exceeds the eight MiB recovery ceiling")
        with temporary.open("wb") as stream:
            stream.write(body)
        temporary.chmod(0o600)
        temporary.replace(path)
        return hashlib.sha256(body).hexdigest()
    finally:
        temporary.unlink(missing_ok=True)


def _plan(request) -> dict:
    """Freeze subquestions, allowed sources and explicit stop conditions before calls."""
    return {"topic": request.topic, "mode": request.mode,
            "subquestions": request.subquestions or [request.topic],
            "source_rules": {"urls": request.urls, "allowed_domains": request.allowed_domains,
                             "supplied_packet_id": request.supplied_packet.packet_id if request.supplied_packet else None,
                             "source_content_role": "data", "new_model_selected_urls": "not_admitted"},
            "limits": request.limits.model_dump(mode="json"),
            "stop_conditions": ["all required branches joined", "revision limit", "unchanged proposal",
                                "call/token/source/deadline limit", "source/account change"],
            "currency_bound": "unverified; a requested USD ceiling blocks submission",
            "hosted_grounding": "separate research_web route; internal searches/tokens/charges unbounded by this SDK"}


def _save(context: dict, status: str) -> str:
    """Persist the actual attempt population without storing account credentials."""
    state = {"run_id": context["run_id"], "request_sha256": context["digest"], "status": status,
             "plan": context["plan"], "branches": context["branches"],
             "sources": context["prepared"]["source_records"],
             "rejections": context["prepared"]["rejections"],
             "source_requests": context["prepared"]["requests"], "execution": context["budget"].report(),
             "source_preparation": {"status": context["preparation_status"], "physical_requests": None,
                                    "required_url_population": len(context["request"].urls),
                                    "required_supplied_ids": [s.id for s in context["request"].supplied_packet.sources]
                                    if context["request"].supplied_packet else []},
             "operation_failure": context.get("failure")}
    return write_state(context["directory"] / "state.json", protect(state, context["selected"][1]))


def _failure_checkpoint(context: dict, status: str) -> dict:
    """A failed disk write cannot erase the live run's actual attempt accounting."""
    try:
        _save(context, status)
    except (OSError, ResearchExecutionFailure) as error:
        return {"status": "write_failed", "error_type": type(error).__name__}
    return {"status": "saved"}


async def _round(context: dict, index: int, revision: int, previous: dict | None):
    """Submit one counted schema-constrained round with no JSON or provider retry."""
    question = context["plan"]["subquestions"][index]
    asyncio.current_task().set_name(f"research:{index}:{revision}")
    kwargs = {"schema": ResearchBranchAnswer, "model": context["selected"][0],
              "api_key": context["selected"][1], "thinking_level": context["request"].thinking_level}
    if context["selected"][2] is not None:
        kwargs["temperature"] = context["selected"][2]
    answer = await GeminiClient.generate_structured(prompt_for(context, question, previous), **kwargs)
    proposal_sha = hashlib.sha256(answer.model_dump_json().encode()).hexdigest()
    answer = ResearchBranchAnswer.model_validate(protect(answer.model_dump(mode="json"), context["selected"][1]))
    result = curate(answer, context, index, revision)
    context["claims"][index] = result.pop("claims")
    return {"revision": revision, "status": "completed", "proposal_sha256": proposal_sha, **result}


async def _branch(context: dict, index: int, semaphore) -> None:
    """Join every round and preserve failures, unchanged proposals and exhausted gaps."""
    branch = context["branches"][index]
    async with semaphore:
        branch["status"] = "running"
        previous = None
        try:
            for revision in range(context["request"].limits.max_revisions + 1):
                record = {"revision": revision, "status": "attempting"}
                branch["rounds"].append(record)
                _save(context, "running")
                result = await _round(context, index, revision, previous)
                record.update(result)
                _save(context, "running")
                if not result["unresolved"]:
                    branch.update(status="completed", stop_reason="no_declared_gaps")
                    return
                if previous is not None and result["proposal_sha256"] == previous["proposal_sha256"]:
                    branch.update(status="partial", stop_reason="unchanged_proposal")
                    return
                previous = result
            branch.update(status="partial", stop_reason="revision_limit")
        except asyncio.CancelledError:
            branch.update(status="cancelled", stop_reason="operation_cancelled")
            if branch["rounds"] and branch["rounds"][-1]["status"] == "attempting":
                branch["rounds"][-1]["status"] = "cancelled"
            raise
        except Exception as error:
            record.update(status="failed", failure=failure(error))
            branch.update(status="failed", stop_reason="retained_failure")
        finally:
            _save(context, "running")


async def _joined(context: dict) -> None:
    """Share one budget across bounded branches and drain cancellation before returning."""
    semaphore = asyncio.Semaphore(context["request"].limits.concurrency)
    tasks = []
    token = single_submission.set(True)
    try:
        with context["budget"].activate():
            tasks = [asyncio.create_task(_branch(context, index, semaphore)) for index in range(len(context["branches"]))]
            await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        drained = asyncio.gather(*tasks, return_exceptions=True)
        while not drained.done():
            try:
                await asyncio.shield(drained)
            except asyncio.CancelledError:
                continue
        drained.result()
        for branch in context["branches"]:
            if branch["status"] == "planned":
                branch.update(status="cancelled", stop_reason="not_submitted_before_cancellation")
        single_submission.reset(token)


def _finish(context: dict, status: str) -> dict:
    """Export source and claim identities with pending production lineage explicit."""
    prepared = context["prepared"]
    claims = prepared["retained_claims"] + [claim for group in context["claims"].values() for claim in group]
    retained_ids = {claim.id for claim in claims}
    for branch in context["branches"]:
        for record in branch["rounds"]:
            for finding in record.get("findings", []):
                finding["retained_in_packet"] = finding["claim_id"] in retained_ids
    packet = EvidencePacket(packet_id="research-" + context["run_id"], sources=context["sources"],
                            claims=claims, lineage=prepared["retained_lineage"],
                            origin_packet_id=context["request"].supplied_packet.packet_id if context["request"].supplied_packet else None)
    validation = validate_evidence_packet(packet, context["directory"])
    if validation["source_errors"]:
        raise ResearchBudgetFailure("Research exported packet source validation failed")
    packet_sha = write_state(context["directory"] / "evidence-packet.json", packet.model_dump(mode="json"))
    state_sha = _save(context, status)
    findings = [finding for b in context["branches"] for r in b["rounds"] for finding in r.get("findings", [])]
    result = ResearchExecutionResponse(status=status, run_id=context["run_id"], request_sha256=context["digest"],
        mode=context["request"].mode, plan=protect(context["plan"], context["selected"][1]),
        sources=protect(prepared["source_records"], context["selected"][1]), rejections=protect(prepared["rejections"], context["selected"][1]),
        branches=context["branches"], findings=findings, execution=context["budget"].report(),
        artifacts={"source_root": str(context["directory"]), "packet_path": str(context["directory"] / "evidence-packet.json"),
                   "packet_sha256": packet_sha, "state_path": str(context["directory"] / "state.json"),
                   "state_sha256": state_sha, "packet_validation": validation,
                   "production_lineage": "retained supplied nodes; new claims require editorial approval and all production stages"}).model_dump(mode="json")
    result = protect(result, context["selected"][1])
    record_result(context["directory"], result, write_state)
    return result


async def _run(context: dict) -> dict:
    """Prepare the fixed source population and execute only its joined rounds."""
    request, selected = context["request"], context["selected"]
    context["prepared"] = await prepare_sources(request, context["directory"])
    context["preparation_status"] = "completed"
    context["sources"] = context["prepared"]["sources"]
    _save(context, "prepared")
    if request.dry_run:
        return _finish(context, "planned")
    if request.mode != "model_only" and not context["sources"]:
        raise ResearchBudgetFailure("No admissible original sources; sourced research was not submitted")
    frozen = {"sources": [s.model_dump(mode="json") for s in context["sources"]],
              "claims": [c.model_dump(mode="json") for c in context["prepared"]["retained_claims"]],
              "lineage": [n.model_dump(mode="json") for n in context["prepared"]["retained_lineage"]]}
    if len(json.dumps(frozen, indent=2, ensure_ascii=False, allow_nan=False).encode()) > MAX_ARTIFACT_BYTES // 2:
        raise ResearchBudgetFailure("Frozen research packet exceeds four MiB serialized; submission blocked")
    for source in context["sources"]:
        if selected[1] and any(secret in source.snapshot.text for secret in
                              {selected[1], quote(selected[1], safe=""), quote_plus(selected[1])}):
            raise ResearchBudgetFailure("Configured account material occurs in a source; submission blocked")
    await _joined(context)
    check_sources(context["directory"], context["sources"], selected)
    partial = bool(context["prepared"]["rejections"] or any(b["status"] != "completed" for b in context["branches"]))
    return _finish(context, "partial" if partial else "complete")


async def execute(request) -> dict:
    """Admit one stable run and retain terminal or ambiguous execution state."""

    selected, identifier = selected_account(), request.run_id or uuid4().hex
    raw = {"request": request.model_dump(mode="json", exclude={"run_id"}), "model": selected[0], "temperature": selected[2],
           "account_sha256": hashlib.sha256(selected[1].encode()).hexdigest()}
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, allow_nan=False).encode()).hexdigest()
    directory = checked_path(str(Path(get_config().cache_dir) / "research" / identifier))
    if directory.exists():
        try:
            return replay(directory, digest, selected)
        except (OSError, ValueError, KeyError) as error:
            return {**failure(error), "run_id": identifier, "request_sha256": digest,
                    "plan": {}, "branches": [], "execution": {"provider_calls": None, "replay_new_calls": 0,
                                                               "accounting_status": "stored_result_rejected"},
                    "state_path": str(directory / "state.json")}
    preflight = None
    if not request.dry_run:
        if request.limits.max_cost_usd is not None:
            preflight = ResearchExecutionFailure("Configured backend has no verified USD ceiling; research was not submitted")
        elif not request.authorize_submission:
            preflight = PermissionError("Research submission authorization is required")
        elif not selected[1]:
            preflight = ResearchExecutionFailure("No configured model account; research was not submitted")
    if preflight:
        return {**failure(preflight), "run_id": identifier, "request_sha256": digest,
                "plan": protect(_plan(request), selected[1]), "branches": [], "execution": {"provider_calls": 0}}
    directory.mkdir(mode=0o700, parents=True)
    context = {"request": request, "selected": selected, "run_id": identifier, "digest": digest,
               "directory": directory, "plan": _plan(request), "sources": [], "claims": {}, "preparation_status": "attempting",
               "prepared": {"source_records": [], "rejections": [], "requests": [], "retained_claims": [], "retained_lineage": []}}
    context["branches"] = [{"id": f"branch-{i}", "subquestion": q, "status": "planned", "rounds": []}
                           for i, q in enumerate(context["plan"]["subquestions"])]
    context["budget"] = ResearchBudget(request.limits, lambda: check_sources(directory, context["sources"], selected))
    try:
        _save(context, "preparing")
        async with asyncio.timeout(request.limits.timeout_seconds):
            return await _run(context)
    except asyncio.CancelledError:
        context["failure"] = {"category": "CANCELLED", "error": "Research caller cancelled the operation"}
        _failure_checkpoint(context, "cancelled")
        raise
    except Exception as error:
        context["failure"] = failure(error)
        checkpoint = _failure_checkpoint(context, "failed")
        return protect({**failure(error), "run_id": identifier, "request_sha256": digest,
                "plan": protect(context["plan"], selected[1]), "branches": context["branches"],
                "execution": {**context["budget"].report(), "failure_checkpoint": checkpoint},
                "state_path": str(directory / "state.json")}, selected[1])
