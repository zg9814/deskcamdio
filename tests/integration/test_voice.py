from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from deskcamdio.services.backend_client import BackendClient
from deskcamdio.services.voice import (
    BYTES_PER_BLOCK,
    LocalCommandRouter,
    VoiceRecorder,
    VoiceService,
    audioop_rms,
    clamp_reply,
    parse_zh_number,
    process_rss_kb,
    trim_history,
)


def test_rms_of_silence_and_sine() -> None:
    silence = b"\x00\x00" * (BYTES_PER_BLOCK // 2)
    assert audioop_rms(silence) == 0
    loud = b"\x00\x80" * 100  # -32768 samples → big rms
    assert audioop_rms(loud) > 1000


def test_recorder_trailing_silence_finishes() -> None:
    recorder = VoiceRecorder()
    speech = b"\x10\x27" * (BYTES_PER_BLOCK // 2)  # ~9999 amplitude
    quiet = b"\x00\x00" * (BYTES_PER_BLOCK // 2)
    assert recorder.feed(speech) == "recording"
    done = ""
    for _ in range(8):
        done = recorder.feed(quiet)
        if done.startswith("done"):
            break
    assert recorder.finished_reason == "trailing-silence"
    assert recorder.blocks


def test_recorder_no_voice_timeout() -> None:
    recorder = VoiceRecorder()
    quiet = b"\x00\x00" * (BYTES_PER_BLOCK // 2)
    for _ in range(25):
        recorder.feed(quiet)
    assert recorder.finished_reason == "no-voice"


def test_recorder_max_length_cap() -> None:
    recorder = VoiceRecorder()
    speech = b"\x10\x27" * (BYTES_PER_BLOCK // 2)
    for _ in range(90):
        recorder.feed(speech)
    assert recorder.finished_reason == "max-length"


@pytest.mark.parametrize(
    ("text", "reply_contains", "action"),
    [
        ("现在几点了", "点", None),
        ("音量调大一点", "好的", "volume_up"),
        ("静音", "静音", "volume_mute"),
        ("帮我拍照", "茄子", "camera.capture"),
        ("播放音乐", "播放", "music.play"),
        ("暂停音乐", "暂停", "music.pause"),
        ("倒计时5分钟", "5分钟", "timer.start"),
        ("记一下买鱼粮", "已记录", "memo.add"),
        ("打开钓鱼", "钓鱼", "navigate"),
        ("网络状态怎么样", "状态栏", "network.report"),
    ],
)
def test_local_router_matches(text, reply_contains, action):
    router = LocalCommandRouter()
    reply, payload = router.match(text)
    assert reply is not None and reply_contains in reply
    if action is not None:
        assert payload is not None and payload["action"] == action


def test_local_router_miss_returns_none() -> None:
    router = LocalCommandRouter()
    assert router.match("今天天气如何") == (None, None)


def test_trim_history_caps_messages_and_chars() -> None:
    history = [{"role": "user", "content": "x" * 500} for _ in range(10)]
    trimmed = trim_history(history)
    assert len(trimmed) <= 6
    total = sum(len(m["content"]) for m in trimmed)
    assert total <= 1200


def test_clamp_reply() -> None:
    assert len(clamp_reply("长" * 500)) == 120


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("42", 42), ("十", 10), ("十二", 12), ("二十", 20), ("两", 2), ("百", None)],
)
def test_parse_zh_number_variants(raw: str, expected: int | None) -> None:
    assert parse_zh_number(raw) == expected


def test_process_rss_parser(monkeypatch) -> None:
    from deskcamdio.services import voice as voice_mod

    class FakePath:
        def __init__(self, _value: str) -> None:
            pass

        def read_text(self, **_kwargs) -> str:
            return "Name:\tworker\nVmRSS:\t12345 kB\n"

    monkeypatch.setattr(voice_mod, "Path", FakePath)
    assert process_rss_kb(42) == 12345


def test_router_rejects_incomplete_strict_commands() -> None:
    router = LocalCommandRouter()
    assert router.match("倒计时很多分钟") == (None, None)
    assert router.match("打开天气") == (None, None)
    reply, payload = router.match("音量调到一二三")
    assert reply == "好的" and payload == {"action": "volume_up", "level": None}


class FakeBackend(BackendClient):
    def __init__(self, reply: str = "云端回复") -> None:
        super().__init__("http://fake")
        self.reply = reply
        self.calls: list[str] = []

    async def transcribe_file(self, wav_path: Path) -> str:
        self.calls.append("asr")
        return "帮我拍照"

    async def chat(self, message: str, history: list[dict[str, str]]) -> str:
        self.calls.append("chat")
        return self.reply


async def test_handle_turn_local_command_short_circuits_cloud(tmp_path: Path) -> None:
    backend = FakeBackend()
    service = VoiceService(backend, LocalCommandRouter(), data_dir=tmp_path)

    async def fake_pcm() -> tuple[bytes, str]:
        return b"\x10\x27" * 100, "trailing-silence"

    service.record_pcm = fake_pcm  # type: ignore[method-assign]
    reply, action = await service.handle_turn()
    assert action == {"action": "camera.capture"}
    assert "chat" not in backend.calls
    assert len(service.history) == 2


async def test_handle_turn_falls_back_to_cloud(tmp_path: Path) -> None:
    backend = FakeBackend(reply="今天晴")
    service = VoiceService(backend, LocalCommandRouter(), data_dir=tmp_path)

    async def fake_pcm() -> tuple[bytes, str]:
        return b"\x00\x00" * 50, "no-voice"

    async def fake_transcribe(pcm: bytes) -> str:
        return "讲个笑话"

    service.record_pcm = fake_pcm  # type: ignore[method-assign]
    service.transcribe = fake_transcribe  # type: ignore[method-assign]
    reply, action = await service.handle_turn()
    assert reply == "今天晴" and action is None
    assert "chat" in backend.calls


async def test_empty_text_returns_nothing(tmp_path: Path) -> None:
    backend = FakeBackend()
    service = VoiceService(backend, LocalCommandRouter(), data_dir=tmp_path)

    async def fake_pcm() -> tuple[bytes, str]:
        return b"", "cancelled"

    service.record_pcm = fake_pcm  # type: ignore[method-assign]
    reply, action = await service.handle_turn()
    assert reply == "" and action is None


async def test_cancel_flag_stops_stream_without_device(tmp_path: Path) -> None:
    service = VoiceService(FakeBackend(), LocalCommandRouter(), data_dir=tmp_path)
    service.cancel()
    pcm, reason = await service.record_pcm()
    assert pcm == b"" and reason == "cancelled"


async def test_request_wav_is_cleaned_after_cloud_asr(tmp_path: Path, monkeypatch) -> None:
    backend = FakeBackend()

    async def transcribe_file(wav_path: Path) -> str:
        assert wav_path.exists(), "wav should exist during upload"
        return "你好"

    backend.transcribe_file = transcribe_file  # type: ignore[method-assign]
    service = VoiceService(backend, LocalCommandRouter(), data_dir=tmp_path)
    text = await service.transcribe(b"\x01\x02" * 16)
    assert text == "你好"
    assert not (tmp_path / "request.wav").exists()


async def test_local_asr_runs_worker_subprocess(tmp_path: Path, monkeypatch) -> None:
    from deskcamdio.services.voice import VoiceService as _S

    class WorkerBackend(FakeBackend):
        async def transcribe_file(self, wav_path):  # noqa: ANN001
            raise AssertionError("cloud path must not be used")

    model_dir = tmp_path / "model"
    model_dir.mkdir()
    service = _S(
        WorkerBackend(),
        LocalCommandRouter(),
        data_dir=tmp_path,
        model_dir=model_dir,
        use_local_asr=True,
    )
    monkeypatch.setenv("DESKCAMDIO_ASR_RUNTIME", "ncnn")
    # Worker exits fast: sherpa_ncnn missing → JSON error line → empty text.
    text = await asyncio.wait_for(service._transcribe_local(b"\x00\x00" * 100), timeout=30)
    assert text == ""


async def test_asr_worker_killed_on_timeout(tmp_path: Path, monkeypatch) -> None:
    """Review fix #5: wait_for expiry must kill the worker, never orphan it."""
    from deskcamdio.services import voice as voice_mod

    killed = {"n": 0}

    class StubProc:
        pid = 4242

        def __init__(self) -> None:
            self.released = asyncio.Event()

        async def communicate(self, _pcm: bytes):
            await self.released.wait()  # hangs until kill() fires
            return b"{}", b""

        def kill(self) -> None:
            killed["n"] += 1
            self.released.set()

        async def wait(self) -> int:
            return 0

    stub = StubProc()

    async def fake_exec(*_args, **_kwargs):
        return stub

    monkeypatch.setattr(voice_mod.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setenv("DESKCAMDIO_ASR_TIMEOUT", "0.05")

    service = VoiceService(
        FakeBackend(),
        LocalCommandRouter(),
        data_dir=tmp_path,
        model_dir=tmp_path,
        use_local_asr=True,
    )
    text = await service._transcribe_local(b"\x00\x00" * 16)
    assert text == ""
    assert killed["n"] == 1
    assert stub.released.is_set()  # kill() unblocked the pipe, no orphan


async def test_transcribe_local_success_and_invalid_json(tmp_path: Path, monkeypatch) -> None:
    from deskcamdio.services import voice as voice_mod

    class StubProc:
        pid = 12
        returncode = 0

        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        async def communicate(self, pcm: bytes):
            assert pcm
            return self.payload, b""

        def kill(self) -> None:
            raise AssertionError("successful workers are not killed")

        async def wait(self) -> int:
            return 0

    payloads = iter(
        [b'{"text":"\xe4\xbd\xa0\xe5\xa5\xbd"}\n', b"not-json", b'{"error":"bad model"}']
    )

    async def fake_exec(*_args, **_kwargs):
        return StubProc(next(payloads))

    monkeypatch.setattr(voice_mod.asyncio, "create_subprocess_exec", fake_exec)
    service = VoiceService(
        FakeBackend(),
        LocalCommandRouter(),
        data_dir=tmp_path,
        model_dir=tmp_path,
        use_local_asr=True,
    )
    assert await service._transcribe_local(b"\x01\x02") == "你好"
    assert await service._transcribe_local(b"\x01\x02") == ""
    assert await service._transcribe_local(b"\x01\x02") == ""
    assert await service.transcribe(b"") == ""


def test_cancel_terminates_live_processes(tmp_path: Path) -> None:
    class Live:
        returncode = None

        def __init__(self) -> None:
            self.terminated = 0

        def terminate(self) -> None:
            self.terminated += 1

    service = VoiceService(FakeBackend(), LocalCommandRouter(), data_dir=tmp_path)
    capture, worker = Live(), Live()
    service._capture_process = capture  # type: ignore[assignment]
    service._asr_process = worker  # type: ignore[assignment]
    service.cancel()
    assert capture.terminated == worker.terminated == 1


def test_sync_recorder_reads_stream_and_terminates(tmp_path: Path, monkeypatch) -> None:
    import io

    speech = b"\x10\x27" * (BYTES_PER_BLOCK // 2)
    quiet = b"\x00\x00" * (BYTES_PER_BLOCK // 2)

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = io.BytesIO(speech + quiet * 7)
            self.terminated = False

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float) -> int:
            assert timeout == 0.5
            return 0

    process = FakeProcess()
    service = VoiceService(FakeBackend(), LocalCommandRouter(), data_dir=tmp_path)
    monkeypatch.setattr(service, "_arecord_process", lambda: process)
    pcm, reason = service._record_stream_sync()
    assert pcm and reason == "trailing-silence" and process.terminated


def test_is_local_asr_mode_accepts_aliases() -> None:
    from deskcamdio.services.voice import is_local_asr_mode

    assert is_local_asr_mode("local")
    assert is_local_asr_mode("local_zipformer")  # legacy alias keeps old env files working
    assert is_local_asr_mode(" LOCAL ")
    assert not is_local_asr_mode("cloud")
    assert not is_local_asr_mode("")
    assert not is_local_asr_mode(None)


def test_asr_worker_main_reports_failure_as_json_line(tmp_path: Path) -> None:
    """Worker must answer one JSON line and exit 0 even when runtime is absent."""
    import io
    import json

    from deskcamdio.services.asr_worker import main

    sink = io.StringIO()
    rc = main(
        ["--model-dir", str(tmp_path), "--runtime", "ncnn"],
        read_input=lambda: b"\x00\x00" * 8,
        output=sink,
    )
    payload = json.loads(sink.getvalue().strip())
    assert rc == 0
    assert "error" in payload  # sherpa missing here; real model error also lands here

    sink2 = io.StringIO()
    rc2 = main(
        ["--model-dir", str(tmp_path), "--runtime", "onnx"],
        read_input=lambda: b"",
        output=sink2,
    )
    payload2 = json.loads(sink2.getvalue().strip())
    assert rc2 == 0
    assert "error" in payload2 or payload2.get("text", "") == ""


# ---- BackendClient --------------------------------------------------------


def test_backend_lazy_pool_not_created_until_request() -> None:
    client = BackendClient("http://backend.example")
    assert client._client is None


def test_backend_chat_retry_on_transport_error() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ReadError("flake", request=request)
        return httpx.Response(200, json={"reply": "ok"})

    async def scenario() -> str:
        client = BackendClient("http://backend.example")
        client._client = httpx.AsyncClient(
            base_url="http://backend.example", transport=httpx.MockTransport(handler)
        )
        try:
            return await client.chat("hi", [])
        finally:
            await client.close()

    assert asyncio.run(scenario()) == "ok"
    assert attempts["n"] == 2
    assert BackendClient("http://x")._client is None  # close() resets pool too


def test_backend_close_resets_pool() -> None:
    async def scenario() -> None:
        client = BackendClient("http://backend.example")
        client._client = httpx.AsyncClient(base_url="http://backend.example")
        await client.close()
        assert client._client is None

    asyncio.run(scenario())


def test_decode_json_helper() -> None:
    assert BackendClient.decode_json(b'{"a": 1}') == {"a": 1}
    assert BackendClient.decode_json(b"not-json") == {}
