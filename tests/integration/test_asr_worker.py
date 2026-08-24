from __future__ import annotations

import io
import json

import pytest

from deskcamdio.services import asr_worker


def test_transcribe_pcm_reports_missing_runtime() -> None:
    result = asr_worker.transcribe_pcm(None, pcm=b"\x00\x00\x00\x00", threads=1, runtime="onnx")
    assert "error" in result


def test_main_writes_single_json_line(monkeypatch, capsys) -> None:
    monkeypatch.setattr(asr_worker, "create_recognizer", lambda *a, **k: object())
    monkeypatch.setattr(asr_worker, "decode_pcm", lambda *a, **k: {"ok": True, "text": "你好"})
    exit_code = asr_worker.main(["--model-dir", "/tmp/m"], read_input=lambda: b"\x00\x00")
    out = capsys.readouterr().out
    assert exit_code == 0
    assert json.loads(out.strip()) == {"ok": True, "text": "你好"}


def test_main_reads_provided_pcm_bytes(monkeypatch, capsys) -> None:
    seen = {}

    def fake(recognizer, pcm):  # noqa: ANN001
        seen["pcm_len"] = len(pcm)
        return {"text": ""}

    monkeypatch.setattr(asr_worker, "create_recognizer", lambda *a, **k: object())
    monkeypatch.setattr(asr_worker, "decode_pcm", fake)
    asr_worker.main(["--model-dir", "/m"], read_input=lambda: b"\x01\x02" * 10)
    assert seen["pcm_len"] == 20


def test_main_reports_errors_as_json(monkeypatch, capsys) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("no model")

    monkeypatch.setattr(asr_worker, "create_recognizer", boom)
    exit_code = asr_worker.main(
        ["--model-dir", "/tmp/m"],
        read_input=lambda: b"",
        output=io.StringIO(),
    )
    assert exit_code == 0  # still exits cleanly; error travels as JSON


def test_main_reports_errors_on_stdout(monkeypatch, capsys) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("no model")

    monkeypatch.setattr(asr_worker, "create_recognizer", boom)
    buffer = io.StringIO()
    asr_worker.main(["--model-dir", "/tmp/m"], read_input=lambda: b"", output=buffer)
    payload = json.loads(buffer.getvalue().strip())
    assert "no model" in str(payload["error"])


@pytest.mark.parametrize("runtime_arg", ["ncnn", "onnx"])
def test_runtime_choice_is_forwarded(monkeypatch, runtime_arg) -> None:
    seen = {}

    def fake(model_dir, threads, runtime):  # noqa: ANN001
        seen["runtime"] = runtime
        return object()

    monkeypatch.setattr(asr_worker, "create_recognizer", fake)
    monkeypatch.setattr(asr_worker, "decode_pcm", lambda *a: {"text": ""})
    asr_worker.main(["--model-dir", "/tmp/m", "--runtime", runtime_arg], read_input=lambda: b"")
    assert seen["runtime"] == runtime_arg
