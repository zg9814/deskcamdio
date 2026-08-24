"""Per-round Zipformer ASR worker.

Loads Zipformer while 16 kHz mono S16 PCM is arriving on stdin, writes one
JSON line to stdout, then exits so the model memory returns to the OS.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

SAMPLE_RATE = 16000


def create_recognizer(model_dir: Path, threads: int, runtime: str) -> Any:
    if runtime == "ncnn":
        try:
            import sherpa_ncnn  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001 - runtime not installed on this host
            raise RuntimeError(f"asr runtime unavailable: {exc}") from exc

        return sherpa_ncnn.Recognizer(
            tokens=str(model_dir / "tokens.txt"),
            encoder_param=str(model_dir / "encoder.ncnn.param"),
            encoder_bin=str(model_dir / "encoder.ncnn.bin"),
            decoder_param=str(model_dir / "decoder.ncnn.param"),
            decoder_bin=str(model_dir / "decoder.ncnn.bin"),
            joiner_param=str(model_dir / "joiner.ncnn.param"),
            joiner_bin=str(model_dir / "joiner.ncnn.bin"),
            num_threads=threads,
        )
    else:
        try:
            import sherpa_onnx
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"asr runtime unavailable: {exc}") from exc

        return sherpa_onnx.OfflineRecognizer.from_zipformer_ctc(
            model=str(model_dir / "model.int8.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=threads,
            decoding_method="greedy_search",
        )


def decode_pcm(recognizer: Any, pcm: bytes) -> dict[str, object]:

    stream = recognizer.create_stream()
    samples = [
        int.from_bytes(pcm[i : i + 2], "little", signed=True) / 32768.0
        for i in range(0, len(pcm) - 1, 2)
    ]
    stream.accept_waveform(SAMPLE_RATE, samples)
    recognizer.decode_stream(stream)
    return {"ok": True, "text": stream.result.text}


def transcribe_pcm(model_dir: Path, pcm: bytes, threads: int, runtime: str) -> dict[str, object]:
    """Compatibility helper for tests and direct one-shot callers."""
    try:
        return decode_pcm(create_recognizer(model_dir, threads, runtime), pcm)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def main(
    argv: list[str] | None = None,
    *,
    read_input: Any = None,
    output: Any = None,
) -> int:
    parser = argparse.ArgumentParser(prog="deskcamdio-asr-worker")
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--runtime", choices=["onnx", "ncnn"], default="onnx")
    args = parser.parse_args(argv)

    reader = read_input if read_input is not None else sys.stdin.buffer.read
    sink = output if output is not None else sys.stdout

    try:
        # Model loading happens before the blocking read completes, in parallel
        # with the parent process recording and streaming microphone PCM.
        recognizer = create_recognizer(args.model_dir, args.threads, args.runtime)
        pcm = reader()
        result = decode_pcm(recognizer, pcm)
    except Exception as exc:  # noqa: BLE001 - report failure as JSON line
        result = {"ok": False, "error": str(exc)}
    sink.write(json.dumps(result, ensure_ascii=False) + "\n")
    with contextlib.suppress(Exception):
        sink.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
