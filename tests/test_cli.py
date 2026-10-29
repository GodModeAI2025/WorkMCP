from __future__ import annotations

from typing import Any

import pytest

from workmcp import __main__ as cli
from workmcp.service import KnowledgeService


class _FakeServer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, transport: str, **kwargs: Any) -> None:
        self.calls.append((transport, kwargs))


@pytest.fixture
def fake_server(monkeypatch: pytest.MonkeyPatch) -> _FakeServer:
    import workmcp.server

    server = _FakeServer()
    monkeypatch.setattr(workmcp.server, "create_server", lambda: server)
    return server


def test_stdio_is_default(fake_server: _FakeServer) -> None:
    cli.main([])
    assert fake_server.calls == [("stdio", {})]


def test_http_without_allowed_hosts_keeps_sdk_default(
    fake_server: _FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WORKMCP_ALLOWED_HOSTS", raising=False)
    cli.main(["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9000"])
    transport, kwargs = fake_server.calls[0]
    assert transport == "streamable-http"
    assert kwargs == {"host": "0.0.0.0", "port": 9000, "transport_security": None}


def test_allowed_hosts_enable_rebinding_protection(fake_server: _FakeServer) -> None:
    cli.main(
        [
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--allowed-host",
            "mcp.firma.de",
            "--allowed-host",
            "10.0.0.5:*",
        ]
    )
    security = fake_server.calls[0][1]["transport_security"]
    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts[:2] == ["mcp.firma.de", "10.0.0.5:*"]
    assert "https://mcp.firma.de" in security.allowed_origins


def test_allowed_hosts_from_environment(fake_server: _FakeServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKMCP_ALLOWED_HOSTS", " localhost:* , mcp.firma.de ,")
    cli.main(["--transport", "streamable-http", "--host", "0.0.0.0"])
    security = fake_server.calls[0][1]["transport_security"]
    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts == ["localhost:*", "mcp.firma.de", "127.0.0.1:*"]


def test_allowed_host_flag_overrides_environment(fake_server: _FakeServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKMCP_ALLOWED_HOSTS", "env.example")
    cli.main(["--transport", "streamable-http", "--allowed-host", "cli.example"])
    hosts = fake_server.calls[0][1]["transport_security"].allowed_hosts
    assert "cli.example" in hosts
    assert "env.example" not in hosts


def test_db_and_offline_flags_set_environment(
    fake_server: _FakeServer, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # setenv records the original state, so the values written by main() are undone after the test
    monkeypatch.setenv("WORKMCP_DB", "platzhalter")
    monkeypatch.setenv("WORKMCP_OFFLINE", "0")
    cli.main(["--db", str(tmp_path / "k.db"), "--offline"])
    import os

    assert os.environ["WORKMCP_DB"] == str(tmp_path / "k.db")
    assert os.environ["WORKMCP_OFFLINE"] == "1"


async def test_archivy_export_uses_configured_dir(service: KnowledgeService, tmp_path) -> None:
    service.settings.archivy_dir = str(tmp_path / "archivy-data")
    service.record_extraction("berufenet:1", aufgaben=[{"text": "Teig herstellen"}])
    out = service.export_knowledge("archivy")
    assert out["ordner"] == str(tmp_path / "archivy-data" / "WorkMCP")
    assert any((tmp_path / "archivy-data" / "WorkMCP").glob("900001-*.md"))
