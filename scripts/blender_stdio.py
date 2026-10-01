"""Observe client EOF before joining cancellation-shielded native tool workers."""

from contextlib import asynccontextmanager


async def forward_input(incoming, outgoing, cleanup) -> None:
    """Close the owned native process before forwarding terminal stream closure."""
    try:
        async for message in incoming:
            await outgoing.send(message)
    finally:
        cleanup()
        await outgoing.aclose()


def eof_transport(cleanup):
    """Create the concrete original-framework transport with native EOF cleanup."""
    import anyio
    from mcp.server.stdio import stdio_server

    @asynccontextmanager
    async def transport():
        async with stdio_server() as (incoming, outgoing):
            sender, receiver = anyio.create_memory_object_stream(0)
            async with anyio.create_task_group() as group:
                group.start_soon(forward_input, incoming, sender, cleanup)
                try:
                    yield receiver, outgoing
                finally:
                    cleanup()
                    group.cancel_scope.cancel()
                    await receiver.aclose()

    return transport
