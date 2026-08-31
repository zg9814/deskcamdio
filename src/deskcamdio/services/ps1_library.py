"""Small, deterministic PlayStation image scanner."""

from __future__ import annotations

import re
from pathlib import Path

PRIMARY_EXTENSIONS = frozenset(
    {".cue", ".chd", ".pbp", ".m3u", ".ccd", ".iso", ".img", ".mdf", ".toc"}
)
_CUE_FILE = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))', re.IGNORECASE)


def _cue_bins(path: Path) -> set[Path]:
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return set()
    targets: set[Path] = set()
    for line in lines:
        match = _CUE_FILE.match(line)
        if match:
            targets.add((path.parent / (match.group(1) or match.group(2))).resolve())
    return targets


def scan_ps1_directory(directory: Path) -> list[Path]:
    """Return launchable images, hiding BIN tracks already represented by CUE."""
    directory.mkdir(parents=True, exist_ok=True)
    files = [path for path in directory.iterdir() if path.is_file()]
    cue_tracks: set[Path] = set()
    for path in files:
        if path.suffix.lower() == ".cue":
            cue_tracks.update(_cue_bins(path))
    launchable = [path for path in files if path.suffix.lower() in PRIMARY_EXTENSIONS]
    launchable.extend(
        path for path in files if path.suffix.lower() == ".bin" and path.resolve() not in cue_tracks
    )
    return sorted(launchable, key=lambda path: path.name.casefold())
