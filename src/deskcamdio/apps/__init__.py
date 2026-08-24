"""Bundled applications. Each subpackage ships an ``app.toml`` descriptor."""

from __future__ import annotations

from pathlib import Path


def apps_root_path() -> Path:
    """Absolute path of the packaged ``apps`` directory."""
    return Path(__file__).resolve().parent
