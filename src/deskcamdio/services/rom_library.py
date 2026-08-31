"""ROM library: validated import, hashing, indexing and local covers."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

MIN_ROM_BYTES = 1024
MAX_ROM_BYTES = 64 * 1024 * 1024
TITLE_OFFSET = 0xA0
CODE_OFFSET = 0xAC
MAKER_OFFSET = 0xB0
FIXED_VALUE_OFFSET = 0xB2  # must be 0x96
HEADER_CHECKSUM_OFFSET = 0xBD
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


class RomError(ValueError):
    pass


@dataclass(frozen=True)
class RomHeader:
    title: str
    game_code: str
    maker_code: str
    fixed_ok: bool
    checksum_ok: bool


def parse_header(data: bytes) -> RomHeader:
    if len(data) < HEADER_CHECKSUM_OFFSET + 1:
        raise RomError("file smaller than GBA header")
    raw_title = data[TITLE_OFFSET : TITLE_OFFSET + 12]
    # Nintendo header checksum (GBA compo): byte at 0xBD is the two's
    # complement of (sum of bytes 0xA0..0xBC + 0x19).
    header_sum = sum(data[TITLE_OFFSET:HEADER_CHECKSUM_OFFSET])
    expected = (-(header_sum + 0x19)) & 0xFF
    return RomHeader(
        title=raw_title.decode("ascii", errors="replace").strip("\x00 ").strip(),
        game_code=data[CODE_OFFSET : CODE_OFFSET + 4].decode("ascii", errors="replace"),
        maker_code=data[MAKER_OFFSET : MAKER_OFFSET + 2].decode("ascii", errors="replace"),
        fixed_ok=data[FIXED_VALUE_OFFSET] == 0x96,
        checksum_ok=data[HEADER_CHECKSUM_OFFSET] == expected,
    )


def validate_file(path: Path) -> RomHeader:
    resolved = path.resolve()
    if not resolved.is_file():
        raise RomError(f"not a file: {path}")
    size = resolved.stat().st_size
    if not MIN_ROM_BYTES <= size <= MAX_ROM_BYTES:
        raise RomError(f"size {size} outside {MIN_ROM_BYTES}-{MAX_ROM_BYTES}")
    with resolved.open("rb") as handle:
        head = handle.read(HEADER_CHECKSUM_OFFSET + 1)
    header = parse_header(head)
    if not header.fixed_ok:
        raise RomError("GBA fixed byte 0x96 missing — not a GBA image")
    if not header.checksum_ok:
        raise RomError("header checksum mismatch")
    return header


HASH_CHUNK_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Streamed digest: constant memory regardless of ROM size."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def safe_slug(text: str) -> str:
    return _SAFE_NAME.sub("_", text).strip("_")[:48] or "rom"


async def index_directory(roms_dir: Path, store: Any) -> int:
    """Scan, hash and index ROMs; returns number of newly added entries.

    Each file is read at most once per scan: validation touches only the
    0xBE-byte header, the digest is streamed in 1 MiB chunks, and files whose
    (size, mtime_ns) match their indexed row are skipped without any read.
    """
    import asyncio

    roms_dir.mkdir(parents=True, exist_ok=True)
    rows = await store.fetch_all("SELECT path, sha256, size_bytes, mtime_ns FROM gba_roms")
    known = {str(row[1]) for row in rows}
    by_path = {str(row[0]): (str(row[1]), int(row[2]), int(row[3])) for row in rows}
    added = 0
    for path in sorted(roms_dir.glob("*.gba")):
        try:
            stat = path.stat()
        except OSError as exc:
            LOGGER.warning("event=rom_rejected file=%s reason=%s", path.name, exc)
            continue
        cached = by_path.get(str(path))
        if cached is not None and cached[1:] == (stat.st_size, stat.st_mtime_ns):
            continue  # unchanged since last index — zero re-reads
        try:
            header = validate_file(path)
        except RomError as exc:
            LOGGER.warning("event=rom_rejected file=%s reason=%s", path.name, exc)
            continue
        digest = await asyncio.to_thread(sha256_file, path)
        if digest in known:
            continue
        if cached is not None:
            # The file at this path was replaced. The store atomically drops
            # that stale path row before inserting the new content identity.
            known.discard(cached[0])
        known.add(digest)
        await store.upsert_rom(
            {
                "sha256": digest,
                "path": str(path),
                "title": path.stem,
                "game_code": header.game_code,
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
        await asyncio.to_thread(generate_cover, roms_dir.parent / "covers", digest, path.stem)
        added += 1
    return added


def generate_cover(covers_dir: Path, sha256: str, title: str) -> Path:
    """Local text-only cover art; never touches the network."""
    from PIL import Image, ImageDraw

    covers_dir.mkdir(parents=True, exist_ok=True)
    out = covers_dir / f"{sha256[:16]}.png"
    if out.exists():
        return out
    image = Image.new("RGB", (160, 200), (24, 34, 52))
    draw = ImageDraw.Draw(image)
    draw.rectangle([8, 8, 151, 191], outline=(90, 120, 170))
    lines = [title[i : i + 12] for i in range(0, min(len(title), 48), 12)] or ["ROM"]
    y = 60
    for line in lines:
        draw.text((18, y), line, fill=(230, 235, 245))
        y += 18
    image.save(out, format="PNG")
    return out
