"""Process-wide store and LangGraph checkpointer handles."""

from contextvars import ContextVar

from app.config import Settings
from app.memory_store import MemoryStore, seed_demo
from app.pg_store import PostgresStore

current_store: ContextVar = ContextVar("g01_store", default=None)
current_checkpointer: ContextVar = ContextVar("g01_checkpointer", default=None)


def get_store():
    store = current_store.get()
    if store is None:
        raise RuntimeError("g01 store is not open")
    return store


def set_store(store) -> None:
    current_store.set(store)


async def open_store(settings: Settings):
    if settings.database_url:
        store = PostgresStore(settings.database_url, settings.schema_path)
        if settings.boot_on_startup:
            await store.apply_schema()
        return store
    if settings.allow_memory_store:
        store = MemoryStore()
        if settings.seed_demo:
            seed_demo(store)
        return store
    raise RuntimeError("Set G01_DATABASE_URL or G01_ALLOW_MEMORY_STORE=1")


class CheckpointerLease:
    def __init__(self, context_manager, saver):
        self.context_manager = context_manager
        self.saver = saver

    async def close(self) -> None:
        await self.context_manager.__aexit__(None, None, None)


async def open_checkpointer(database_url: str) -> CheckpointerLease:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    context_manager = AsyncPostgresSaver.from_conn_string(dsn)
    saver = await context_manager.__aenter__()
    await saver.setup()
    return CheckpointerLease(context_manager, saver)
