"""Command line entry point: ``workmcp`` (stdio) or ``workmcp --transport streamable-http``."""

from __future__ import annotations

import argparse
import os


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="workmcp", description="WorkMCP – MCP-Server für einen deutschen Job-Graphen")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="stdio (z. B. Claude Code lokal) oder streamable-http (zentraler Server)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host für streamable-http (Standard 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port für streamable-http (Standard 8000)")
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        metavar="HOST[:PORT]",
        help="Erlaubter Host-Header für streamable-http (mehrfach möglich, z. B. 'mcp.firma.de' oder "
        "'10.0.0.5:*'; Standard aus WORKMCP_ALLOWED_HOSTS, kommagetrennt); aktiviert den Schutz gegen "
        "DNS-Rebinding auch bei --host 0.0.0.0",
    )
    parser.add_argument("--db", help="Pfad zur Wissensdatenbank (überschreibt WORKMCP_DB)")
    parser.add_argument("--offline", action="store_true", help="Nur aus dem Gedächtnis antworten, keine Netzzugriffe")
    args = parser.parse_args(argv)
    if args.db:
        os.environ["WORKMCP_DB"] = args.db
    if args.offline:
        os.environ["WORKMCP_OFFLINE"] = "1"

    from .server import create_server

    server = create_server()
    if args.transport == "stdio":
        server.run("stdio")
    else:
        allowed = args.allowed_host or [
            h.strip() for h in os.environ.get("WORKMCP_ALLOWED_HOSTS", "").split(",") if h.strip()
        ]
        security = None
        if allowed:
            from mcp.server.transport_security import TransportSecuritySettings

            hosts = list(dict.fromkeys([*allowed, "127.0.0.1:*", "localhost:*"]))
            security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=hosts,
                allowed_origins=[f"http://{h}" for h in hosts] + [f"https://{h}" for h in hosts],
            )
        server.run("streamable-http", host=args.host, port=args.port, transport_security=security)


if __name__ == "__main__":
    main()
