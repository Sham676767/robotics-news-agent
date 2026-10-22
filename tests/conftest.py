import socket
from pathlib import Path

import httpx
import pytest

from app.legal_draft import load_legal_draft


@pytest.fixture(autouse=True)
def block_external_apis(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("External API calls must be mocked in tests")

    monkeypatch.setattr(httpx.Client, "send", blocked)
    monkeypatch.setattr(httpx.AsyncClient, "send", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def legal_package():
    return load_legal_draft(Path(__file__).parent / "fixtures" / "legal_draft.json")
