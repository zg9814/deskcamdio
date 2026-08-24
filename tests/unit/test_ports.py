from __future__ import annotations

import pytest

from deskcamdio.platform.ports import unavailable


def test_unavailable_helper_raises_descriptive_error() -> None:
    boom = unavailable("Picamera2 capture")
    with pytest.raises(RuntimeError, match="Pi hardware"):
        boom()


def test_unavailable_helper_accepts_any_args() -> None:
    boom = unavailable("GPIO")
    try:
        boom(1, two="args")
    except RuntimeError:
        pass  # expected
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")
