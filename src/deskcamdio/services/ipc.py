"""Length-prefixed JSON header + binary body framing shared by workers."""

from __future__ import annotations

import json
import struct
import uuid
from dataclasses import dataclass, field
from typing import Any

MAX_HEADER = 64 * 1024
MAX_BODY = 12 * 1024 * 1024


class ProtocolError(RuntimeError):
    pass


@dataclass(slots=True)
class Message:
    type: str  # request | response | event
    name: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    body_length: int = 0
    timestamp: float = 0.0
    ok: bool = True
    error: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    body: bytes = b""

    def encode_header(self) -> bytes:
        header = {
            "type": self.type,
            "name": self.name,
            "id": self.id,
            "body_length": len(self.body),
            "timestamp": self.timestamp,
            "ok": self.ok,
        }
        if not self.ok:
            header["error"] = self.error
        if len(self.body) > MAX_BODY:
            raise ProtocolError("body too large")
        header.update(self.payload)
        raw = json.dumps(header, ensure_ascii=False).encode("utf-8")
        if len(raw) > MAX_HEADER:
            raise ProtocolError("header too large")
        return struct.pack(">I", len(raw)) + raw


def decode_header(data: bytes) -> tuple[dict[str, Any], int]:
    if len(data) < 4:
        raise ProtocolError("short header")
    (length,) = struct.unpack(">I", data[:4])
    if length > MAX_HEADER:
        raise ProtocolError("header too large")
    header = json.loads(data[4 : 4 + length].decode("utf-8"))
    return header, int(header.get("body_length", 0))


def new_request(name: str, **payload: Any) -> Message:
    return Message(type="request", name=name, payload=payload)


def response_for(request: Message, *, ok: bool = True, error: str = "", **payload: Any) -> Message:
    return Message(
        type="response",
        name=request.name,
        id=request.id,
        ok=ok,
        error=error,
        payload=payload,
    )


# ---- socket transport ----------------------------------------------------


def send_message(sock: Any, message: Message) -> None:
    sock.sendall(message.encode_header() + message.body)


def recv_exact(sock: Any, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("peer closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_message(sock: Any) -> Message:
    raw_length = recv_exact(sock, 4)
    (length,) = struct.unpack(">I", raw_length)
    if length > MAX_HEADER:
        raise ProtocolError("header too large")
    raw_header = recv_exact(sock, length)
    header = json.loads(raw_header.decode("utf-8"))
    body_length = int(header.get("body_length", 0))
    if body_length > MAX_BODY:
        raise ProtocolError("body too large")
    body = recv_exact(sock, body_length) if body_length else b""
    return Message(
        type=str(header.get("type", "request")),
        name=str(header.get("name", "")),
        id=str(header.get("id", "")),
        timestamp=float(header.get("timestamp", 0.0)),
        ok=bool(header.get("ok", True)),
        error=str(header.get("error", "")),
        payload={
            k: v
            for k, v in header.items()
            if k not in {"type", "name", "id", "body_length", "timestamp", "ok", "error"}
        },
        body=body,
    )
