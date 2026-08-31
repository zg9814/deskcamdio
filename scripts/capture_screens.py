"""Capture theme/page/app screenshots into work/screenshots (guide §15)."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

import pygame

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deskcamdio.core.lifecycle import RouteState  # noqa: E402
from deskcamdio.core.runtime import DeviceRuntime, RunState  # noqa: E402
from deskcamdio.ui.themes import THEMES  # noqa: E402


def os_env() -> None:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


def build_contact_sheet(paths: list[Path], destination: Path) -> None:
    columns = 4
    cell_width, cell_height = 250, 274
    rows = (len(paths) + columns - 1) // columns
    sheet = pygame.Surface((columns * cell_width, rows * cell_height))
    sheet.fill((31, 38, 56))
    font = pygame.font.Font(None, 20)
    for index, path in enumerate(paths):
        column, row = index % columns, index // columns
        x, y = column * cell_width, row * cell_height
        image = pygame.image.load(str(path))
        preview = pygame.transform.smoothscale(image, (224, 224))
        sheet.blit(preview, (x + 13, y + 12))
        label = font.render(path.stem, True, (230, 237, 246))
        sheet.blit(label, (x + 13, y + 244))
    pygame.image.save(sheet, str(destination))


async def main() -> None:
    os_env()
    root = Path(__file__).resolve().parents[1]
    out_dir = root / "work" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    captured: list[Path] = []
    data_dir = root / "work" / "simulator-data"
    run_dir = root / "work" / "simulator-run"
    for generated_dir in (data_dir, run_dir):
        if generated_dir.exists():
            shutil.rmtree(generated_dir)

    runtime = DeviceRuntime(
        data_dir=data_dir,
        run_dir=run_dir,
        headless=True,
        fps=240,
        health_interval=3600,
    )
    await runtime.initialize()
    surface = runtime.screen
    assert surface is not None and runtime.manager is not None

    async def snap(name: str, *, global_back: bool = False) -> None:
        surface.fill((0, 0, 0))
        runtime.manager.update(1 / 30)  # type: ignore[union-attr]
        runtime.manager.render(surface)
        if global_back:
            runtime._render_global_back(surface)  # noqa: SLF001
        path = out_dir / f"{name}.png"
        pygame.image.save(surface, str(path))
        captured.append(path)
        print("saved", name)

    async def enter(app_id: str, args: dict[str, str] | None = None) -> None:
        await runtime.manager.enter(RouteState(app_id=app_id, args=args or {}))

    for theme_id in sorted(THEMES):
        assert runtime.theme is not None
        runtime.theme.select(theme_id)
        await snap(f"standby-{theme_id}")

    # All product screenshots use the shipping default theme.
    runtime.theme.select("aquatic")

    await enter("launcher", {"page": "0"})
    await snap("launcher-page1")
    launcher_host = runtime.manager._mounted["launcher"]  # noqa: SLF001
    launcher_host.app.page = 1  # type: ignore[union-attr]
    await snap("launcher-page2")
    launcher_host.app.page = 2  # type: ignore[union-attr]
    await snap("launcher-page3")

    for app_id in (
        "camera",
        "gallery",
        "music",
        "gba",
        "ps1",
        "fishing",
        "memo",
        "pomodoro",
        "settings",
    ):
        await enter(app_id)
        await asyncio.sleep(0.15)
        await snap(f"app-{app_id}")

    await runtime.store.add_memo(
        "这是一条用于验证长中文自动换行的备忘内容，不能越界、截断或显示成方块。"
    )
    await enter("memo")
    await snap("state-long-chinese")

    await enter("music")
    music = runtime.manager._mounted["music"].app  # noqa: SLF001
    music.current = Path("A-Very-Long-Song-Title-For-Layout-Verification.mp3")
    music._lyrics = [  # noqa: SLF001
        (0.0, "This is a deliberately long lyric line that must wrap instead of showing ellipsis")
    ]
    await snap("state-long-lyrics")

    await enter("fishing")
    from deskcamdio.apps.fishing.app import GameModal

    runtime.manager._mounted["fishing"].app.modal = GameModal(  # noqa: SLF001
        "鱼跑了！", "收线太慢，鱼挣脱了", 1.2, (222, 148, 34)
    )
    await snap("state-dialog")
    fishing = runtime.manager._mounted["fishing"].app  # noqa: SLF001
    fishing.modal = None
    fishing._start_trip()  # noqa: SLF001
    fishing.update(0.5)
    await snap("state-fishing-sea")

    await enter("pomodoro")
    runtime.manager._mounted["pomodoro"].app.running = True  # noqa: SLF001
    await snap("state-pressed")

    await enter("camera")
    runtime.machine.transition(RunState.LAUNCHER, reason="screenshot")
    runtime.machine.transition(RunState.APP, reason="screenshot")
    await snap("state-global-back", global_back=True)
    camera = runtime.manager._mounted["camera"].app  # noqa: SLF001
    camera._preview_surface = None  # noqa: SLF001
    camera._error = "IMX708 暂不可用，请检查排线后重试"  # noqa: SLF001
    await snap("state-camera-fault")

    await enter("settings")
    settings = runtime.manager._mounted["settings"].app  # noqa: SLF001
    settings.page = 2
    settings._bt_candidates = [  # noqa: SLF001
        {"address": "00:11:22:33:44:55", "name": "Bluetooth Gamepad", "connected": False}
    ]
    await snap("state-bluetooth-controller", global_back=True)
    settings.page = 3
    await asyncio.sleep(0.1)
    await snap("state-diagnostics")

    build_contact_sheet(captured, out_dir / "simulator-contact-sheet.png")
    print("saved simulator-contact-sheet")
    await runtime.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
