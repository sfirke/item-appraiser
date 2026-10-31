import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if a test tries to reach the API or a photo URL."""

    def refuse(*args, **kwargs):
        raise AssertionError("tests must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
