from __future__ import annotations

import asyncio

import httpx
import pytest

from deskcamdio.services.backend_client import MAX_TTS_BYTES, BackendClient


def _client_with(handler) -> BackendClient:
    client = BackendClient("http://backend.example")
    client._client = httpx.AsyncClient(
        base_url="http://backend.example", transport=httpx.MockTransport(handler)
    )
    return client


def test_health_roundtrip() -> None:
    async def scenario() -> dict:
        client = _client_with(
            lambda request: httpx.Response(200, json={"status": "ok", "version": "1"})
        )
        try:
            return await client.health()
        finally:
            await client.close()

    assert asyncio.run(scenario())["status"] == "ok"


def test_transcribe_file_posts_multipart(tmp_path) -> None:
    wav = tmp_path / "request.wav"
    wav.write_bytes(b"RIFF-fake")

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content_type"] = request.headers.get("content-type", "")
        return httpx.Response(200, json={"text": "你好"})

    async def scenario() -> str:
        client = _client_with(handler)
        try:
            return await client.transcribe_file(wav)
        finally:
            await client.close()

    assert asyncio.run(scenario()) == "你好"
    assert "multipart/form-data" in seen["content_type"]


def test_stream_tts_delivers_chunks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "audio/wav; charset=utf-8"},
            content=b"x" * 40_000,
        )

    async def scenario() -> tuple[bytes, str]:
        chunks: list[bytes] = []
        types: list[str] = []

        async def consume(stream, media_type):  # noqa: ANN001
            types.append(media_type)
            async for chunk in stream:
                chunks.append(chunk)

        client = _client_with(handler)
        try:
            await client.stream_tts("你好", consume)
        finally:
            await client.close()
        return b"".join(chunks), types[0]

    audio, media_type = asyncio.run(scenario())
    assert len(audio) == 40_000
    assert media_type == "audio/wav"


def test_stream_tts_enforces_cap() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"y" * (MAX_TTS_BYTES + 1024))

    async def scenario() -> str:
        async def consume(stream, media_type):  # noqa: ANN001
            async for _chunk in stream:
                pass

        client = _client_with(handler)
        try:
            await client.stream_tts("长文本", consume)
        except RuntimeError as exc:
            return str(exc)
        finally:
            await client.close()
        return ""

    assert "8MiB" in asyncio.run(scenario())


def test_chat_http_error_propagates() -> None:
    async def scenario() -> None:
        client = _client_with(lambda request: httpx.Response(500))
        try:
            await client.chat("hi", [])
        finally:
            await client.close()

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(scenario())
