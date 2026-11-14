"""Tests never reach the network: a connection off this machine fails the test."""

lazy import socket
lazy import subprocess
lazy from collections.abc import Callable
lazy from pathlib import Path
lazy from typing import Any

lazy import pytest

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    resolve = socket.getaddrinfo
    connect: Callable[[socket.socket, Any], None] = socket.socket.connect

    def local_resolve(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host not in _LOOPBACK:
            raise AssertionError(f"Test resolved {host!r} over the network")
        return resolve(host, *args, **kwargs)

    def local_connect(self: socket.socket, address: Any) -> None:
        if isinstance(address, tuple) and address[0] not in _LOOPBACK:
            raise AssertionError(f"Test connected to {address!r}")
        connect(self, address)

    run: Callable[..., Any] = subprocess.run

    def local_run(args: Any, *rest: Any, **kwargs: Any) -> Any:
        # The GitHub CLI talks to GitHub whatever it is asked to do.
        if Path(str(args[0])).name == "gh":
            raise AssertionError(f"Test ran the GitHub CLI: {args!r}")
        return run(args, *rest, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", local_resolve)
    monkeypatch.setattr(subprocess, "run", local_run)
    monkeypatch.setattr(socket.socket, "connect", local_connect)
