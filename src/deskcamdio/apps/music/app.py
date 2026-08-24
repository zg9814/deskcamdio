"""Music: local library playback with lyrics-ready now-playing pane."""

from __future__ import annotations

import re
from pathlib import Path

import pygame

from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.ui import components
from deskcamdio.ui.aquarium import ambient, seabed
from deskcamdio.ui.typography import draw_wrapped, render_text

AUDIO_SUFFIXES = {".mp3", ".ogg", ".wav"}


class MusicApp(App):
    def __init__(self) -> None:
        self._context: RuntimeContext | None = None
        self.tracks: list[Path] = []
        self.current: Path | None = None
        self._rows: dict[int, pygame.Rect] = {}
        self._buttons: dict[str, pygame.Rect] = {}
        self._lyrics: list[tuple[float, str]] = []

    async def mount(self, context: RuntimeContext) -> None:
        self._context = context

    def _music_dir(self) -> Path:
        context = self._context
        assert context is not None
        directory = context.data_dir / "music"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    async def enter(self, route: RouteState) -> None:
        self.tracks = sorted(
            p for p in self._music_dir().iterdir() if p.suffix.lower() in AUDIO_SUFFIXES
        )

    def handle_input(self, event: pygame.event.Event) -> None:
        context = self._context
        if context is None or event.type != pygame.MOUSEBUTTONDOWN:
            return
        pos = event.pos
        for key, rect in self._buttons.items():
            if rect.collidepoint(pos):
                if key == "toggle":
                    self._toggle()
                break
        else:
            for index, rect in self._rows.items():
                if rect.collidepoint(pos) and index < len(self.tracks):
                    self._play(self.tracks[index])
                    break

    def _play(self, track: Path) -> None:
        context = self._context
        assert context is not None
        if context.audio.play_music(track):
            self.current = track
            self._lyrics = self._load_lyrics(track.with_suffix(".lrc"))

    @staticmethod
    def _load_lyrics(path: Path) -> list[tuple[float, str]]:
        if not path.exists():
            return []
        parsed: list[tuple[float, str]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)", line.strip())
            if match and match.group(3).strip():
                parsed.append(
                    (int(match.group(1)) * 60 + float(match.group(2)), match.group(3).strip())
                )
        return sorted(parsed)

    def _current_lyric(self) -> str:
        if not self._lyrics:
            return ""
        position = max(0, pygame.mixer.music.get_pos()) / 1000.0 if pygame.mixer.get_init() else 0.0
        current = self._lyrics[0][1]
        for timestamp, line in self._lyrics:
            if timestamp > position:
                break
            current = line
        return current

    def _toggle(self) -> None:
        context = self._context
        assert context is not None
        if context.audio.music_playing or self.current is not None:
            if context.audio.music_playing:
                context.audio.pause_music()
            else:
                context.audio.resume_music()

    def update(self, delta_seconds: float) -> None:
        del delta_seconds
        context = self._context
        if context is not None and context.audio.poll_music_finished():
            self.current = None
            self._lyrics.clear()

    def render(self, surface: pygame.Surface) -> None:
        assert self._context is not None
        theme = self._context.theme.tokens
        ticks = pygame.time.get_ticks() / 1000.0
        ambient(surface, theme, ticks * 0.35)
        title = render_text("音乐 · 本地曲库", 20, theme.text_primary, bold=True)
        surface.blit(title, (16, 12))

        now = pygame.Rect(16, 48, 448, 126)
        components.glass_card(surface, now, theme, alpha=232)
        pygame.draw.circle(surface, theme.surface_elevated, (76, 111), 42)
        pygame.draw.circle(surface, theme.accent, (76, 111), 25, 4)
        pygame.draw.circle(surface, theme.text_primary, (76, 111), 5)
        components.icon(surface, "music", (76, 111), 26, theme.accent)
        now_title = self.current.stem if self.current else "暂无播放"
        draw_wrapped(
            surface,
            now_title,
            pygame.Rect(132, 58, 280, 52),
            16,
            theme.text_primary,
            line_gap=0,
        )
        lyric = self._current_lyric() if self.current else ""
        if lyric:
            draw_wrapped(
                surface,
                lyric,
                pygame.Rect(132, 112, 300, 54),
                14,
                theme.text_secondary,
                line_gap=2,
            )
        else:
            subtitle = render_text(
                "本地音乐" if self.current else "把音乐文件放入 music 文件夹",
                14,
                theme.text_secondary,
            )
            surface.blit(subtitle, (132, 132))

        self._rows.clear()
        row_rect = pygame.Rect(16, 190, 448, 52)
        for index, track in enumerate(self.tracks[:4]):
            rect = row_rect.copy()
            rect.y += index * 58
            selected = self.current == track
            components.row(
                surface,
                rect,
                track.stem,
                theme,
                trailing=track.suffix[1:].upper(),
                selected=selected,
            )
            self._rows[index] = rect

        if not self.tracks:
            seabed(surface, theme, ticks * 0.25)
            hint = render_text("曲库还是空的", 18, theme.text_secondary, bold=True)
            surface.blit(hint, hint.get_rect(center=(240, 250)))

        toggle = pygame.Rect(190, 414, 100, 48)
        self._buttons["toggle"] = toggle
        label = (
            "暂停" if (self._context.audio.music_playing if self._context else False) else "播放"
        )
        components.button(surface, toggle, label, theme)

    async def leave(self, reason: LeaveReason) -> None:
        # Playback continues across pages by design; nothing to stop here.
        del reason

    async def dispose(self) -> None:
        self._context = None
        self.tracks.clear()
        self._rows.clear()
        self._buttons.clear()
        self._lyrics.clear()
