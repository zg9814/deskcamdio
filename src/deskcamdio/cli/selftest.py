"""Headless self-test used by release installs to validate the environment.

Verifies that the package imports, the version resolves, and pygame can
initialise its display and font subsystems under a dummy video driver.
"""

from __future__ import annotations

import os
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    from deskcamdio import __version__

    try:
        import pygame

        pygame.display.init()
        pygame.font.init()
        surface = pygame.display.set_mode((480, 480))
        ok = surface.get_size() == (480, 480)
    except Exception:  # noqa: BLE001 - selftest must report, never crash the installer
        return 1
    finally:
        try:
            import pygame

            pygame.quit()
        except Exception:  # noqa: BLE001
            pass
    print(f"deskcamdio {__version__} selftest {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
