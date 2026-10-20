"""Tests ciblés du lanceur (probe de port, loopback)."""

import socket
from pathlib import Path

from launcher import port_is_free

ROOT = Path(__file__).resolve().parents[1]


def test_port_is_free_when_nothing_listens():
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    holder.close()
    assert port_is_free(port) is True


def test_port_is_free_false_when_listener_active():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        assert port_is_free(port) is False
    finally:
        listener.close()


def test_launcher_loopback_only_and_reuseaddr_probe():
    text = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "127.0.0.1" in text
    assert "0.0.0.0" not in text
    assert "SO_REUSEADDR" in text
