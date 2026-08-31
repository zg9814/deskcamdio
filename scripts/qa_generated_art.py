"""Validate generated UI raster assets against the checked-in manifest."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "art" / "generated" / "processed"
MANIFEST = ROOT / "art" / "generated" / "asset-manifest.csv"


def main() -> int:
    with MANIFEST.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    problems: list[str] = []
    expected = {
        Path(row["file"]).name: (int(row["width"]), int(row["height"]))
        for row in rows
    }
    for row in rows:
        source = ROOT / row["source_file"]
        if not source.is_file():
            problems.append(f"source missing: {row['source_file']}")
    files = sorted(
        path
        for path in ASSET_DIR.glob("*.png")
        if "contact-sheet" not in path.name
    )
    rgba_count = 0
    binary_alpha_count = 0

    for path in files:
        if path.name not in expected:
            problems.append(f"manifest missing row: {path.name}")
            continue
        with Image.open(path) as image:
            if image.size != expected[path.name]:
                problems.append(
                    f"size mismatch: {path.name}: {image.size} != {expected[path.name]}"
                )
            if image.getbbox() is None:
                problems.append(f"blank image: {path.name}")
            if "A" in image.mode:
                rgba_count += 1
                values = {
                    value
                    for value, count in enumerate(image.getchannel("A").histogram())
                    if count
                }
                if values.issubset({0, 255}):
                    binary_alpha_count += 1
                else:
                    problems.append(
                        f"non-binary alpha: {path.name}: {len(values)} values"
                    )

    for name in expected:
        if not (ASSET_DIR / name).is_file():
            problems.append(f"file missing: {name}")

    print(f"manifest rows: {len(rows)}")
    print(f"processed assets: {len(files)}")
    print(f"RGBA assets: {rgba_count}")
    print(f"binary-alpha RGBA assets: {binary_alpha_count}")
    print(f"problems: {len(problems)}")
    for problem in problems:
        print(f"- {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
