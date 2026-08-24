"""IPC framing loopback over socketpair (works on Windows and POSIX)."""

from __future__ import annotations

import socket
import threading

import pytest

from deskcamdio.cli.camera_worker import CameraWorker
from deskcamdio.services.ipc import (
    Message,
    ProtocolError,
    new_request,
    recv_message,
    send_message,
)


def test_message_roundtrip_with_body() -> None:
    left, right = socket.socketpair()
    try:
        message = Message(type="request", name="preview")
        message.payload = {"size": 0}
        message.body = b"\xff\xd8fakejpeg"
        send_message(left, message)

        received = recv_message(right)
        assert received.name == "preview"
        assert received.body == message.body
    finally:
        left.close()
        right.close()


def test_oversized_body_rejected() -> None:
    from deskcamdio.services.ipc import MAX_BODY

    left, right = socket.socketpair()
    try:
        huge = Message(type="response", name="preview")
        huge.body = b"\x00" * (MAX_BODY + 1)
        with pytest.raises(ProtocolError):
            send_message(left, huge)
    finally:
        left.close()
        right.close()


def _serve_until_close(worker: CameraWorker, server_side: socket.socket) -> None:
    server_side.settimeout(5.0)
    while True:
        request = recv_message(server_side)
        header = {
            "type": "request",
            "name": request.name,
            "id": request.id,
            **request.payload,
            "body_length": len(request.body),
        }
        send_message(server_side, worker.handle(header, request.body))
        if request.name == "close":
            break


def test_worker_serve_loop_over_socketpair() -> None:
    """Drive the real handler through the wire format without AF_UNIX."""
    worker = CameraWorker()
    left, right = socket.socketpair()
    pump = threading.Thread(target=_serve_until_close, args=(worker, right), daemon=True)
    try:
        left.settimeout(5.0)
        pump.start()
        for request_name in ("ping", "close"):
            send_message(left, new_request(request_name))
            response = recv_message(left)
            assert response.type == "response"
            assert response.ok is True
            assert response.name == request_name
    finally:
        left.close()
        right.close()
        pump.join(timeout=2.0)


def test_unknown_request_over_wire() -> None:
    worker = CameraWorker()
    left, right = socket.socketpair()
    done = threading.Event()

    def serve_one() -> None:
        request = recv_message(right)
        header = {"type": "request", "name": request.name, "id": request.id}
        send_message(right, worker.handle(header, b""))
        done.set()

    pump = threading.Thread(target=serve_one, daemon=True)
    try:
        left.settimeout(5.0)
        pump.start()
        send_message(left, new_request("bogus"))
        response = recv_message(left)
        assert response.ok is False
        done.wait(timeout=2.0)
    finally:
        left.close()
        right.close()
        pump.join(timeout=2.0)


def test_peer_disconnect_raises_connection_error() -> None:
    left, right = socket.socketpair()
    right.close()
    left.settimeout(2.0)
    with pytest.raises((ConnectionError, OSError)):
        recv_message(left)
    left.close()
