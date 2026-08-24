"""Device CLI: boots the DeviceRuntime (simulator or real hardware)."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import sys
from pathlib import Path

from deskcamdio import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deskcamdio-device")
    parser.add_argument("--version", action="version", version=f"deskcamdio {__version__}")
    parser.add_argument("--headless", action="store_true", help="dummy SDL drivers")
    parser.add_argument("--frames", type=int, default=None, help="exit after N frames")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("DESKCAMDIO_DATA_DIR", "/var/lib/deskcamdio")),
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=Path(os.environ.get("DESKCAMDIO_RUN_DIR", "/run/deskcamdio")),
    )
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--selftest", action="store_true", help="run environment self-test and exit"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if os.environ.get("DESKCAMDIO_HEADLESS") == "1":
        args.headless = True
    if args.selftest:
        from deskcamdio.cli.selftest import main as selftest_main

        return selftest_main()

    from deskcamdio.core.runtime import DeviceRuntime

    runtime = DeviceRuntime(
        data_dir=args.data_dir,
        run_dir=args.run_dir,
        headless=args.headless,
        fps=args.fps,
    )

    async def boot() -> None:
        loop = asyncio.get_running_loop()
        current = asyncio.current_task()
        if current is None:  # pragma: no cover - always a task under asyncio.run
            return
        # SIGHUP arrives when the tty is hung up (e.g. getty contention);
        # treat every termination signal as a graceful stop, never a crash.
        for sig in (signal.SIGTERM, signal.SIGINT, getattr(signal, "SIGHUP", None)):
            if sig is None:
                continue
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, current.cancel)
        await runtime.initialize()
        await runtime.run(frame_limit=args.frames)

    try:
        asyncio.run(boot())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("terminated", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
