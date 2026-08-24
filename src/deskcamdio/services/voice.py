"""Voice assistant pipeline.

Fixed VAD parameters (guide §8): 16 kHz mono S16, 100 ms blocks, RMS 420
speech threshold, 700 ms trailing silence, 2 s no-voice abort, 8 s cap.
Local deterministic commands win before any cloud round-trip.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from deskcamdio.services.backend_client import BackendClient

LOGGER = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
BLOCK_MS = 100
BYTES_PER_BLOCK = SAMPLE_RATE * 2 * BLOCK_MS // 1000
RMS_SPEECH = 420
TRAILING_SILENCE_MS = 700
NO_VOICE_TIMEOUT_S = 2.0
MAX_RECORD_SECONDS = 8.0

MAX_HISTORY_MESSAGES = 6
MAX_HISTORY_CHARS = 1200
MAX_REPLY_CHARS = 120

# DESKCAMDIO_ASR_MODE switch values that enable the on-device worker.
# 'local_zipformer' kept as a legacy alias of 'local' so old env files work.
LOCAL_ASR_MODES = frozenset({"local", "local_zipformer"})


def process_rss_kb(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="ascii").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def is_local_asr_mode(raw: str | None) -> bool:
    return (raw or "").strip().lower() in LOCAL_ASR_MODES


RuleResult = tuple[str, dict[str, Any] | None] | None


def parse_zh_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {
        "零": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    if value in digits:
        return digits[value]
    return None


class VoiceRecorder:
    """VAD state machine over PCM blocks (testable with synthetic input)."""

    def __init__(self) -> None:
        self.speech_started = False
        self.silence_ms_after_speech = 0
        self.total_ms = 0.0
        self.blocks: list[bytes] = []
        self.finished_reason = ""

    def feed(self, block: bytes) -> str:
        """Returns '', 'recording', or 'done:<reason>'."""
        if self.finished_reason:
            return "done"
        rms = audioop_rms(block)
        self.total_ms += BLOCK_MS
        hit_cap = self.total_ms >= MAX_RECORD_SECONDS * 1000

        if rms >= RMS_SPEECH:
            self.speech_started = True
            self.silence_ms_after_speech = 0
            self.blocks.append(block)
            if hit_cap:
                self.finished_reason = "max-length"
                return "done"
            return "recording"

        if self.speech_started:
            self.silence_ms_after_speech += BLOCK_MS
            self.blocks.append(block)
            if self.silence_ms_after_speech >= TRAILING_SILENCE_MS:
                self.finished_reason = "trailing-silence"
                return "done"
        else:
            self.blocks.append(block)
            if self.total_ms >= NO_VOICE_TIMEOUT_S * 1000:
                self.finished_reason = "no-voice"
                return "done"

        if hit_cap:
            self.finished_reason = "max-length"
            return "done"
        return ""


def audioop_rms(block: bytes) -> int:
    """Pure-Python RMS over little-endian S16 samples (audioop is gone in 3.13)."""
    count = len(block) // 2
    if count == 0:
        return 0
    total = 0
    for index in range(0, count * 2, 2):
        sample = int.from_bytes(block[index : index + 2], "little", signed=True)
        total += sample * sample
    return int((total / count) ** 0.5)


class LocalCommandRouter:
    """Deterministic offline commands; returns reply text or None."""

    def __init__(self, actions: dict[str, Callable[[dict[str, Any]], None]] | None = None):
        self.actions = actions or {}

    def match(self, text: str) -> tuple[str | None, dict[str, Any] | None]:
        normalized = re.sub(r"\s+", "", text or "")
        for rule in (
            self._match_time,
            self._match_volume,
            self._match_mute,
            self._match_capture,
            self._match_play,
            self._match_pause,
            self._match_timer,
            self._match_memo,
            self._match_open,
            self._match_network,
        ):
            matched = rule(normalized)
            if matched is not None:
                return matched
        return None, None

    @staticmethod
    def _match_time(text: str) -> RuleResult:
        if "几点" in text or "时间" in text:
            return f"现在是{time.strftime('%H点%M分')}", None
        return None

    @staticmethod
    def _match_volume(text: str) -> RuleResult:
        found = re.search(
            r"音量(?:调到|设置为|加大|增加|调大)?([零一二两三四五六七八九十\d]{0,3})", text
        )
        if not found:
            return None
        level = parse_zh_number(found.group(1)) if found.group(1) else None
        if level is not None:
            level = max(0, min(100, level))
        return "好的", {"action": "volume_up", "level": level}

    @staticmethod
    def _match_mute(text: str) -> RuleResult:
        if "静音" in text:
            return "已静音", {"action": "volume_mute"}
        return None

    @staticmethod
    def _match_capture(text: str) -> RuleResult:
        if "拍照" in text or "拍一张" in text:
            return "茄子", {"action": "camera.capture"}
        return None

    @staticmethod
    def _match_play(text: str) -> RuleResult:
        if "播放" in text and ("音乐" in text or "歌" in text):
            return "开始播放", {"action": "music.play"}
        return None

    @staticmethod
    def _match_pause(text: str) -> RuleResult:
        if "暂停" in text:
            return "已暂停", {"action": "music.pause"}
        return None

    @staticmethod
    def _match_timer(text: str) -> RuleResult:
        found = re.search(r"(?:倒计时|计时|番茄钟)([零一二两三四五六七八九十\d]+)分钟", text)
        if not found:
            return None
        parsed = parse_zh_number(found.group(1))
        if parsed is None:
            return None
        minutes = max(1, min(parsed, 120))
        return f"已设置{minutes}分钟倒计时", {"action": "timer.start", "minutes": minutes}

    @staticmethod
    def _match_memo(text: str) -> RuleResult:
        body = re.sub(r"^(记一下|备忘)", "", text)
        if body == text:
            return None
        return "已记录", {"action": "memo.add", "body": body}

    _KNOWN_APPS = {
        "相机": "camera",
        "相册": "gallery",
        "音乐": "music",
        "游戏": "gba",
        "钓鱼": "fishing",
        "备忘录": "memo",
        "番茄钟": "pomodoro",
        "设置": "settings",
    }

    @classmethod
    def _match_open(cls, text: str) -> RuleResult:
        found = re.search(r"打开(.+)", text)
        if not found:
            return None
        target = found.group(1)
        app_id = cls._KNOWN_APPS.get(target)
        if app_id is None:
            return None
        return f"打开{target}", {"action": "navigate", "app_id": app_id}

    @staticmethod
    def _match_network(text: str) -> RuleResult:
        if ("网络" in text or "蓝牙" in text) and ("状态" in text or "怎么样" in text):
            return "请看状态栏，正在检查设备状态", {"action": "network.report"}
        return None


def trim_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    trimmed = history[-MAX_HISTORY_MESSAGES:]
    total = sum(len(m.get("content", "")) for m in trimmed)
    while trimmed and total > MAX_HISTORY_CHARS:
        total -= len(trimmed[0].get("content", ""))
        trimmed = trimmed[1:]
    return trimmed


def clamp_reply(text: str) -> str:
    return text[:MAX_REPLY_CHARS]


class VoiceService:
    def __init__(
        self,
        backend: BackendClient,
        router: LocalCommandRouter,
        *,
        data_dir: Path,
        model_dir: Path | None = None,
        use_local_asr: bool = False,
    ) -> None:
        self.backend = backend
        self.router = router
        self.data_dir = data_dir
        self.model_dir = model_dir
        self.use_local_asr = use_local_asr
        self.history: list[dict[str, str]] = []
        self.state = "idle"
        self.last_error = ""
        self.abort = False
        self._asr_process: asyncio.subprocess.Process | None = None
        self._capture_process: asyncio.subprocess.Process | None = None

    def cancel(self) -> None:
        """Abort an in-flight recording at the next 100 ms block boundary."""
        self.abort = True
        for process in (self._capture_process, self._asr_process):
            if process is not None and process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()

    # ---- recording ---------------------------------------------------------

    def _arecord_process(self) -> subprocess.Popen[bytes] | None:
        arecord = shutil.which("arecord")
        if arecord is None:
            return None
        return subprocess.Popen(  # noqa: S603 - fixed argv
            [
                arecord,
                "-q",
                "-t",
                "raw",
                "-f",
                "S16_LE",
                "-r",
                str(SAMPLE_RATE),
                "-c",
                "1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def _record_stream_sync(self) -> tuple[bytes, str]:
        """100 ms blocks through the VAD; returns (pcm, finished_reason).

        Recording stops at trailing silence / no-voice / max-length / cancel
        without waiting for the full capture window.
        """
        recorder = VoiceRecorder()
        process = self._arecord_process()
        if process is None or process.stdout is None:
            # No capture device: honour cancel, otherwise report no-voice.
            return b"", "cancelled" if self.abort else ""
        try:
            while True:
                if self.abort:
                    recorder.finished_reason = "cancelled"
                    break
                block = process.stdout.read(BYTES_PER_BLOCK)
                if not block:
                    break
                status = recorder.feed(block)
                if len(block) < BYTES_PER_BLOCK:
                    break
                if status.startswith("done"):
                    break
            return b"".join(recorder.blocks), recorder.finished_reason or "eof"
        finally:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:  # pragma: no cover
                process.kill()

    async def record_pcm(self) -> tuple[bytes, str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._record_stream_sync)

    # ---- transcription -------------------------------------------------------

    async def transcribe(self, pcm: bytes) -> str:
        if not pcm:
            return ""
        wav_path = self.data_dir / "request.wav"
        _write_wav(wav_path, pcm)
        try:
            if self.use_local_asr and self.model_dir is not None:
                return await self._transcribe_local(pcm)
            return await self.backend.transcribe_file(wav_path)
        except Exception as exc:  # noqa: BLE001 - network errors degrade gracefully
            self.last_error = str(exc)
            LOGGER.warning("ASR failed: %s", exc)
            return ""
        finally:
            wav_path.unlink(missing_ok=True)

    async def _transcribe_local(self, pcm: bytes) -> str:
        """One-shot worker subprocess so ONNX memory dies with the round."""
        model_dir = self.model_dir
        assert model_dir is not None
        runtime_kind = os.getenv("DESKCAMDIO_ASR_RUNTIME", "onnx")
        threads = os.getenv("DESKCAMDIO_ASR_THREADS", "2")
        timeout_s = float(os.getenv("DESKCAMDIO_ASR_TIMEOUT", "12"))
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "deskcamdio.services.asr_worker",
            "--model-dir",
            str(model_dir),
            "--runtime",
            runtime_kind,
            "--threads",
            threads,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(process.communicate(pcm), timeout=timeout_s)
        except TimeoutError:
            # The worker holds hundreds of MB of model memory — never orphan it.
            process.kill()
            with contextlib.suppress(Exception):
                await process.wait()
            LOGGER.warning("event=asr_worker_timeout pid=%s killed=true", process.pid)
            return ""
        try:
            payload = json.loads(stdout.decode("utf-8", errors="replace") or "{}")
        except json.JSONDecodeError:
            return ""
        if "error" in payload:
            LOGGER.warning("local ASR worker error: %s", payload["error"])
            return ""
        return str(payload.get("text", ""))

    async def _record_and_transcribe_local(self) -> tuple[str, str]:
        """Start model loading and stream 100 ms microphone blocks concurrently."""
        assert self.model_dir is not None
        arecord = shutil.which("arecord")
        if arecord is None:
            return "", "capture-unavailable"
        worker = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "deskcamdio.services.asr_worker",
            "--model-dir",
            str(self.model_dir),
            "--runtime",
            os.getenv("DESKCAMDIO_ASR_RUNTIME", "onnx"),
            "--threads",
            os.getenv("DESKCAMDIO_ASR_THREADS", "2"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        capture = await asyncio.create_subprocess_exec(
            arecord,
            "-q",
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-r",
            str(SAMPLE_RATE),
            "-c",
            "1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._asr_process = worker
        self._capture_process = capture
        recorder = VoiceRecorder()
        started = time.monotonic()
        peak_rss_kb = 0
        try:
            assert capture.stdout is not None and worker.stdin is not None
            while not self.abort:
                block = await capture.stdout.read(BYTES_PER_BLOCK)
                if not block:
                    break
                peak_rss_kb = max(peak_rss_kb, process_rss_kb(worker.pid))
                recorder.feed(block)
                worker.stdin.write(block)
                await worker.stdin.drain()
                if len(block) < BYTES_PER_BLOCK or recorder.finished_reason:
                    break
            worker.stdin.close()
            with contextlib.suppress(Exception):
                await worker.stdin.wait_closed()
            assert worker.stdout is not None
            timeout_s = float(os.getenv("DESKCAMDIO_ASR_TIMEOUT", "12"))
            line = await asyncio.wait_for(worker.stdout.readline(), timeout=timeout_s)
            await asyncio.wait_for(worker.wait(), timeout=1.0)
            payload = json.loads(line.decode("utf-8", errors="replace") or "{}")
            if payload.get("error"):
                self.last_error = str(payload["error"])
                return "", recorder.finished_reason
            return str(payload.get("text", "")), recorder.finished_reason
        except (TimeoutError, json.JSONDecodeError, OSError) as exc:
            self.last_error = str(exc)
            if worker.returncode is None:
                worker.kill()
                await worker.wait()
            return "", recorder.finished_reason or "worker-failed"
        finally:
            if capture.returncode is None:
                capture.terminate()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(capture.wait(), timeout=0.5)
            if worker.returncode is None:
                worker.terminate()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(worker.wait(), timeout=1.0)
            self._capture_process = None
            self._asr_process = None
            LOGGER.info(
                "event=asr_round duration_ms=%d peak_rss_kb=%d exit_reason=%s",
                round((time.monotonic() - started) * 1000),
                peak_rss_kb,
                recorder.finished_reason or ("cancelled" if self.abort else "eof"),
            )

    # ---- full turn -----------------------------------------------------------

    async def handle_turn(self) -> tuple[str, dict[str, Any] | None]:
        """Record → ASR → local command → cloud chat. Returns (reply, action)."""
        self.state = "listening"
        self.abort = False
        started = time.monotonic()
        exit_reason = "unknown"
        route_type = "none"
        try:
            if self.use_local_asr and self.model_dir is not None:
                text, exit_reason = await self._record_and_transcribe_local()
            else:
                pcm, exit_reason = await self.record_pcm()
                self.state = "transcribing"
                text = await self.transcribe(pcm)
            if not text.strip():
                return "", None

            reply, action = self.router.match(text)
            if reply is None:
                route_type = "cloud"
                self.state = "thinking"
                try:
                    reply = await self.backend.chat(text, trim_history(self.history))
                    reply = clamp_reply(reply)
                except Exception as exc:  # noqa: BLE001
                    self.last_error = str(exc)
                    reply = "网络不可用，本地指令可以继续用"
            else:
                route_type = "local"
            self.history.append({"role": "user", "content": text})
            self.history.append({"role": "assistant", "content": reply})
            self.history = trim_history(self.history)
            return reply, action
        finally:
            self.state = "idle"
            LOGGER.info(
                "event=voice_turn duration_ms=%d exit_reason=%s route=%s",
                round((time.monotonic() - started) * 1000),
                exit_reason,
                route_type,
            )


def _write_wav(path: Path, pcm: bytes) -> None:
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)
