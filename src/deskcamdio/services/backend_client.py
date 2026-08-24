"""Cloud backend client.

The httpx pool is created lazily on first request so an offline device never
holds sockets (guide §8). All cloud endpoints are the existing /v1 contract.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)

MAX_TTS_BYTES = 8 * 1024 * 1024


class BackendClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 45.0,
        access_token: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {access_token}"} if access_token else None
        self._timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._timeout,
                trust_env=False,
                headers=self._headers,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request_with_retry(
        self, operation: Callable[[], Awaitable[httpx.Response]]
    ) -> httpx.Response:
        for attempt in range(2):
            try:
                return await operation()
            except httpx.TransportError:
                if attempt:
                    raise
                await asyncio.sleep(0.35)
        raise RuntimeError("unreachable")

    async def health(self) -> dict[str, Any]:
        response = await self._request_with_retry(lambda: self._http.get("/v1/health"))
        response.raise_for_status()
        return dict(response.json())

    async def chat(self, message: str, history: list[dict[str, str]]) -> str:
        payload = {"message": message, "history": history}
        response = await self._request_with_retry(lambda: self._http.post("/v1/chat", json=payload))
        response.raise_for_status()
        data = response.json()
        return str(data.get("reply", ""))

    async def transcribe_file(self, wav_path: Path) -> str:
        payload = wav_path.read_bytes()

        def upload() -> Any:
            return self._http.post(
                "/v1/asr",
                files={"audio": (wav_path.name, payload, "audio/wav")},
            )

        response = await self._request_with_retry(upload)
        response.raise_for_status()
        return str(response.json().get("text", ""))

    async def stream_tts(
        self, text: str, consume: Callable[[AsyncIterator[bytes], str], Awaitable[None]]
    ) -> None:
        """Stream TTS audio chunks (16 KiB) with an 8 MiB hard cap."""
        request = {"text": text}

        async def runner() -> None:
            async with self._http.stream("POST", "/v1/tts/stream", json=request) as response:
                response.raise_for_status()
                media_type = response.headers.get("content-type", "audio/wav").split(";")[0]

                async def limited() -> AsyncIterator[bytes]:
                    total = 0
                    async for chunk in response.aiter_bytes(16 * 1024):
                        total += len(chunk)
                        if total > MAX_TTS_BYTES:
                            raise RuntimeError("TTS 回复超过 8MiB，已中断")
                        yield chunk

                await consume(limited(), media_type)

        await runner()

    @staticmethod
    def decode_json(data: bytes) -> dict[str, Any]:
        with contextlib.suppress(json.JSONDecodeError):
            return dict(json.loads(data))
        return {}
