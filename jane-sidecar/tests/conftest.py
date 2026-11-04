import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.gemini_flow import gemini_override
from app.main import create_app
from app.memory_store import MemoryStore, seed_demo


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("G01_DATABASE_URL", raising=False)
    monkeypatch.setenv("G01_ALLOW_MEMORY_STORE", "1")
    monkeypatch.setenv("G01_GEMINI_API_KEY", "")
    monkeypatch.setenv("G01_ADMIN_TOKEN", "")
    monkeypatch.setenv("G01_CHATWOOT_API_TOKEN", "")
    monkeypatch.setenv("G01_STRIPE_SECRET_KEY", "")
    get_settings.cache_clear()
    token = gemini_override.set(lambda _model, _messages, _complexity: "Noted.")
    yield
    gemini_override.reset(token)
    get_settings.cache_clear()


@pytest.fixture
def store():
    memory = MemoryStore()
    seed_demo(memory)
    return memory


@pytest.fixture
def client(store):
    with TestClient(create_app(store)) as test_client:
        yield test_client
