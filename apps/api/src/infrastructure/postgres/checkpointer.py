"""PostgreSQL checkpointer setup for LangGraph.

In production, uses langgraph-checkpoint-postgres for durable state.
In tests, uses MemorySaver. The graph doesn't know which checkpointer
is backing it -- dependency injection via compile(checkpointer=...).

Usage:
    from apps.api.src.infrastructure.postgres.checkpointer import get_checkpointer

    checkpointer = await get_checkpointer(settings)
    compiled = graph.compile(checkpointer=checkpointer)
"""

from langgraph.checkpoint.memory import MemorySaver

from apps.api.src.config.settings import Settings


async def get_checkpointer(settings: Settings | None = None):
    """Get the appropriate checkpointer for the environment.

    In production: PostgreSQL-backed (langgraph-checkpoint-postgres).
    In tests / development: MemorySaver (in-memory, no DB needed).

    The graph is agnostic to which checkpointer backs it.
    """
    if settings is None:
        return MemorySaver()

    # Try to use PostgreSQL checkpointer if available
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        conn_string = (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}"
            f"/{settings.postgres_db}"
        )
        checkpointer = AsyncPostgresSaver.from_conn_string(conn_string)
        await checkpointer.setup()
        return checkpointer
    except ImportError:
        # langgraph-checkpoint-postgres not installed -- fall back to memory
        return MemorySaver()


__all__ = ["get_checkpointer"]
