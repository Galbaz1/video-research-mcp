"""Execute text-only Agent SDK queries with bounded concurrency and timeouts."""

from __future__ import annotations

import asyncio
import logging
import time

import claude_agent_sdk

from .config import get_config
from .redaction import redact_text
from .types import AgentResult

logger = logging.getLogger(__name__)


async def run_agent_query(
    prompt: str,
    *,
    system_prompt: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    timeout: int | None = None,
) -> AgentResult:
    """Generate text without granting the scene model tools or workspace access.

    Args:
        prompt: Scene generation request.
        system_prompt: Scene instructions.
        model: Override the configured Claude model.
        max_turns: Override the configured turn limit.
        timeout: Override the configured timeout in seconds.

    Returns:
        Text and terminal success or error, including elapsed time.
    """
    cfg = get_config()
    timeout = timeout if timeout is not None else cfg.agent_timeout
    options = claude_agent_sdk.ClaudeAgentOptions(
        max_turns=max_turns if max_turns is not None else cfg.agent_max_turns,
        model=model or cfg.agent_model,
        system_prompt=system_prompt,
        tools=[],
        strict_mcp_config=True,
        setting_sources=[],
        # Override only the child environment; concurrent calls retain the parent context.
        env={"CLAUDECODE": ""},
    )
    start = time.monotonic()
    text_parts: list[str] = []
    terminal: claude_agent_sdk.ResultMessage | None = None
    error = None
    try:
        async with asyncio.timeout(timeout):
            async for message in claude_agent_sdk.query(prompt=prompt, options=options):
                if isinstance(message, claude_agent_sdk.AssistantMessage):
                    if message.error:
                        error = f"Agent response error: {message.error}"
                    text_parts.extend(
                        block.text for block in message.content
                        if isinstance(block, claude_agent_sdk.TextBlock)
                    )
                elif isinstance(message, claude_agent_sdk.ResultMessage):
                    terminal = message
                    if message.is_error or message.subtype != "success":
                        error = "; ".join(message.errors or []) or message.result or message.subtype
                    elif message.terminal_reason in {"aborted_streaming", "aborted_tools"}:
                        error = f"Agent query ended: {message.terminal_reason}"
    except TimeoutError:
        error = f"Agent query timed out after {timeout}s"
    except Exception as exc:
        error = redact_text(str(exc))

    full_text = (terminal.result if terminal and terminal.result else "\n".join(text_parts))
    if error is None and terminal is None:
        error = "Agent query ended without a terminal result"
    if error is None and not full_text.strip():
        error = "Empty response from agent"
    return AgentResult(
        text="" if error else full_text,
        success=error is None,
        duration_seconds=time.monotonic() - start,
        error=redact_text(error) if error else None,
    )


async def run_parallel_queries(
    queries: list[dict],
    *,
    concurrency: int | None = None,
) -> list[AgentResult]:
    """Run bounded queries and preserve input order, including failed results.

    Args:
        queries: Keyword arguments accepted by ``run_agent_query``.
        concurrency: Override the configured maximum number of active queries.

    Returns:
        One result per input query, in input order.
    """
    concurrency = concurrency if concurrency is not None else get_config().agent_concurrency
    if not 1 <= concurrency <= 10:
        raise ValueError("concurrency must be between 1 and 10")
    semaphore = asyncio.Semaphore(concurrency)

    async def _run_with_semaphore(query_kwargs: dict) -> AgentResult:
        """Acquire a query slot before starting the SDK subprocess."""
        async with semaphore:
            return await run_agent_query(**query_kwargs)

    logger.info("Starting %d queries (concurrency=%d)", len(queries), concurrency)
    return list(await asyncio.gather(*[_run_with_semaphore(q) for q in queries]))
