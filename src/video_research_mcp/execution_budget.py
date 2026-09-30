"""Meter actual request attempts and conservatively retain unobserved usage."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json

from google.genai import types

from .models.execution import ExecutionLimits
from .retry import with_retry

_active: ContextVar[ExecutionBudget | None] = ContextVar("execution_budget", default=None)


def current_budget() -> ExecutionBudget | None:
    """Return the budget shared by the current run's awaited tasks."""
    return _active.get()


class ExecutionBudget:
    """Reserve each count/generation operation before its external transport call."""

    def __init__(self, limits: ExecutionLimits):
        self.limits = limits
        self.calls: list[dict] = []
        self.reserved_tokens = 0
        self.windows = 0
        self.frames = 0
        self.violation = False

    @contextmanager
    def activate(self):
        """Scope accounting to this run without altering other concurrent requests."""
        token = _active.set(self)
        try:
            yield self
        finally:
            _active.reset(token)

    def reserve_call(self, kind: str, *, model: str, tokens: int = 0) -> dict:
        """Reserve each media transmission, including token counts and failed retries."""
        if self.violation or len(self.calls) >= self.limits.max_calls:
            raise ValueError("Execution budget exhausted: provider call limit")
        if self.reserved_tokens + tokens > self.limits.max_tokens:
            raise ValueError("Execution budget exhausted: token reservation limit")
        frames = self.frames + self.limits.requested_frames
        if self.windows + 1 > self.limits.max_windows or frames > self.limits.max_frames:
            raise ValueError("Execution budget exhausted: window/frame limit")
        record = {
            "kind": kind,
            "model": model,
            "reserved_tokens": tokens,
            "status": "usage_unknown",
            "usage": None,
        }
        self.calls.append(record)
        self.reserved_tokens += tokens
        self.windows += 1
        self.frames = frames
        return record

    def reconcile(self, record: dict, response) -> None:
        """Keep reported counts separate from reservations and missing telemetry."""
        record["finish_reasons"] = [
            candidate.finish_reason for candidate in response.candidates or []
        ]
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            record["status"] = "completed_usage_unknown"
            return
        data = usage.model_dump(exclude_none=True)
        record.update(status="completed", usage=data)
        total = data.get("total_token_count")
        if isinstance(total, int) and total >= 0:
            self.reserved_tokens += total - record["reserved_tokens"]
            record["reconciled_tokens"] = total
            if total > record["reserved_tokens"] or self.reserved_tokens > self.limits.max_tokens:
                self.violation = True
                record["status"] = "provider_exceeded_reservation"

    async def count_input(self, client, model: str, contents, config) -> int:
        """Count prepared input; retain a separate conservative schema reservation."""
        record = self.reserve_call("count_tokens", model=model)
        try:
            counted = await client.aio.models.count_tokens(
                model=model,
                contents=contents,
                config=types.CountTokensConfig(http_options=config.http_options),
            )
        except Exception:
            record["status"] = "failed_usage_unknown"
            raise
        if type(counted.total_tokens) is not int or counted.total_tokens < 0:
            raise ValueError("Provider token count is unknown; bounded generation is blocked")
        record.update(status="completed", counted_input_tokens=counted.total_tokens)
        schema = config.response_json_schema
        schema_bytes = len(json.dumps(schema, sort_keys=True).encode()) if schema else 0
        return counted.total_tokens + schema_bytes

    async def generate(self, client, model: str, contents, config):
        """Meter each retry and disable additional hidden SDK transport retries."""
        config.max_output_tokens = self.limits.max_output_tokens
        config.http_options = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
        input_tokens = await self.count_input(client, model, contents, config)

        async def attempt():
            record = self.reserve_call(
                "generate_content",
                model=model,
                tokens=input_tokens + self.limits.max_output_tokens,
            )
            try:
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
            except Exception:
                record["status"] = "failed_usage_unknown"
                raise
            self.reconcile(record, response)
            return response

        return await with_retry(attempt)

    def report(self) -> dict:
        """Export nonsecret usage evidence without inventing prices or savings."""
        measured = [r["reconciled_tokens"] for r in self.calls if "reconciled_tokens" in r]
        generation = [r for r in self.calls if r["kind"] == "generate_content"]
        return {
            "limits": self.limits.model_dump(),
            "provider_calls": len(self.calls),
            "requested_windows": self.windows,
            "requested_frames": self.frames,
            "observed_frames": None,
            "counted_tokens_method": "provider_count_plus_schema_utf8_bytes",
            "reserved_or_reconciled_tokens": self.reserved_tokens,
            "measured_total_tokens": sum(measured) if measured else None,
            "usage_complete": bool(generation)
            and all("reconciled_tokens" in r for r in generation),
            "provider_exceeded_reservation": self.violation,
            "generation_truncated": any(
                "MAX_TOKENS" in r.get("finish_reasons", []) for r in generation
            ),
            "calls": self.calls,
            "cost_usd": None,
            "saved_tokens": None,
            "charge_bound_verified": False,
        }
