"""Single-photo filter worker (guide §8).

Runs as its own process so Pillow/numpy never load in the UI main process.
One photo per invocation; writes to ``<dst>.part`` then atomically replaces;
on any failure the original stays untouched and a non-zero exit reports it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

FILTERS = ("ccd", "leica", "bw")


def make_thumbnail(src: Path, dst: Path, size: int = 128) -> None:
    from PIL import Image, ImageOps

    with Image.open(src) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (size, size), (8, 12, 18))
        canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_suffix(dst.suffix + ".part")
    canvas.save(part, format="JPEG", quality=82)
    part.replace(dst)


def apply_filter(src: Path, dst: Path, name: str) -> None:
    from PIL import Image, ImageEnhance, ImageOps

    with Image.open(src) as original:
        image = original.convert("RGB")
    if name == "bw":
        image = ImageOps.grayscale(image).convert("RGB")
    elif name == "ccd":
        # Warm cast + slight desaturation approximating cheap digicam sensors.
        r, g, b = image.split()
        r = r.point(lambda v: min(255, int(v * 1.08)))
        b = b.point(lambda v: int(v * 0.92))
        image = Image.merge("RGB", (r, g, b))
        image = ImageEnhance.Color(image).enhance(0.85)
    elif name == "leica":
        image = ImageEnhance.Contrast(image).enhance(1.12)
        image = ImageEnhance.Color(image).enhance(1.06)

    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_suffix(dst.suffix + ".part")
    image.save(part, format="JPEG", quality=90)
    with part.open("rb+") as handle:
        import os

        os.fsync(handle.fileno())
    part.replace(dst)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deskcamdio-photo-worker")
    parser.add_argument("--src", required=True, type=Path)
    parser.add_argument("--dst", required=True, type=Path)
    parser.add_argument("--filter", dest="filter_name", choices=FILTERS)
    parser.add_argument("--thumbnail", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.thumbnail:
            make_thumbnail(args.src, args.dst)
        elif args.filter_name:
            apply_filter(args.src, args.dst, args.filter_name)
        else:
            parser.error("--filter or --thumbnail is required")
    except Exception as exc:  # noqa: BLE001 - report, keep original intact
        print(f"photo-worker error: {exc}", file=sys.stderr)
        return 1
    print(args.dst)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
