"""Normalize AI-generated raster candidates and build an art review sheet.

The source images remain untouched in ``art/generated``.  Production candidates
are written to ``art/generated/processed`` with deterministic dimensions and
real alpha.  RGB images with a baked near-white checkerboard are cleaned by
flood-filling only near-neutral background pixels connected to the canvas edge,
so enclosed white highlights remain intact.
"""

from __future__ import annotations

import csv
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "art" / "generated"
OUTPUT_DIR = SOURCE_DIR / "processed"


@dataclass(frozen=True)
class AssetSpec:
    source: str
    output: str
    size: tuple[int, int]
    fit: tuple[int, int]
    purpose: str
    background: str = "alpha"
    crop_quarter: int | None = None
    crop_count: int | None = None
    crop_index: int = 0
    isolate_largest: bool = False
    align: str = "center"


SPECS = (
    AssetSpec(
        "hero-fish-source-v1.png",
        "hero-fish-64-v1.png",
        (64, 64),
        (54, 48),
        "Standby hero fish and visual identity seed",
        align="bottom",
    ),
    AssetSpec(
        "aquatic-props-source-v2.png",
        "seaweed-slender-64-v1.png",
        (64, 64),
        (54, 56),
        "Aquarium foreground decoration",
        background="checker",
        crop_quarter=0,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "aquatic-props-source-v2.png",
        "plant-broadleaf-64-v1.png",
        (64, 64),
        (56, 56),
        "Aquarium foreground decoration",
        background="checker",
        crop_quarter=1,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "aquatic-props-source-v2.png",
        "coral-bush-64-v1.png",
        (64, 64),
        (56, 54),
        "Aquarium foreground decoration",
        background="checker",
        crop_quarter=2,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "aquatic-props-source-v2.png",
        "clam-64-v1.png",
        (64, 64),
        (52, 48),
        "Aquarium foreground decoration",
        background="checker",
        crop_quarter=3,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "empty-gallery-source-v1.png",
        "empty-gallery-160x112-v1.png",
        (160, 112),
        (112, 96),
        "Gallery empty-state illustration",
    ),
    AssetSpec(
        "empty-memo-source-v1.png",
        "empty-memo-160x112-v1.png",
        (160, 112),
        (112, 96),
        "Memo empty-state illustration",
        background="checker",
    ),
    AssetSpec(
        "gba-cartridge-source-v1.png",
        "gba-cartridge-96x128-v1.png",
        (96, 128),
        (84, 116),
        "Generic GBA-library placeholder art",
    ),
    AssetSpec(
        "ps1-disc-case-source-v1.png",
        "ps1-disc-case-96x128-v1.png",
        (96, 128),
        (88, 108),
        "Generic optical-disc library placeholder art",
    ),
    AssetSpec(
        "empty-music-source-v1.png",
        "empty-music-160x112-v1.png",
        (160, 112),
        (120, 92),
        "Music empty-state illustration",
    ),
    AssetSpec(
        "empty-focus-source-v1.png",
        "empty-focus-160x112-v1.png",
        (160, 112),
        (112, 96),
        "Focus timer empty-state illustration",
    ),
    AssetSpec(
        "fishing-fish-family-source-v1.png",
        "fishing-common-64x48-v1.png",
        (64, 48),
        (58, 40),
        "Fishing common fish candidate",
        crop_quarter=0,
        isolate_largest=True,
    ),
    AssetSpec(
        "fishing-fish-family-source-v1.png",
        "fishing-uncommon-64x48-v1.png",
        (64, 48),
        (54, 42),
        "Fishing uncommon fish candidate",
        crop_quarter=1,
        isolate_largest=True,
    ),
    AssetSpec(
        "fishing-fish-family-source-v1.png",
        "fishing-rare-64x48-v1.png",
        (64, 48),
        (58, 40),
        "Fishing rare fish candidate",
        crop_quarter=2,
        isolate_largest=True,
    ),
    AssetSpec(
        "fishing-fish-family-source-v1.png",
        "fishing-legendary-64x48-v1.png",
        (64, 48),
        (56, 42),
        "Fishing legendary fish candidate",
        crop_quarter=3,
        isolate_largest=True,
    ),
    AssetSpec(
        "hero-fish-source-v1.png",
        "hero-swim-frame-1-v1.png",
        (64, 64),
        (54, 48),
        "Hero swim animation frame 1 (approved seed)",
        align="bottom",
    ),
    AssetSpec(
        "hero-swim-sheet-source-v1.png",
        "hero-swim-frame-2-v1.png",
        (64, 64),
        (54, 48),
        "Hero swim animation frame 2 candidate",
        background="checker",
        crop_quarter=1,
        align="bottom",
    ),
    AssetSpec(
        "hero-swim-sheet-source-v1.png",
        "hero-swim-frame-3-v1.png",
        (64, 64),
        (54, 48),
        "Hero swim animation frame 3 candidate",
        background="checker",
        crop_quarter=2,
        align="bottom",
    ),
    AssetSpec(
        "hero-swim-sheet-source-v1.png",
        "hero-swim-frame-4-v1.png",
        (64, 64),
        (54, 48),
        "Hero swim animation frame 4 candidate",
        background="checker",
        crop_quarter=3,
        align="bottom",
    ),
    AssetSpec(
        "companion-fish-family-source-v1.png",
        "companion-orange-64-v1.png",
        (64, 64),
        (54, 48),
        "Orange companion fish",
        crop_count=2,
        crop_index=0,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "companion-fish-family-source-v1.png",
        "companion-yellow-64-v1.png",
        (64, 64),
        (54, 48),
        "Yellow companion fish",
        crop_count=2,
        crop_index=1,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "hero-blink-sheet-source-v1.png",
        "hero-blink-frame-1-v1.png",
        (64, 64),
        (54, 48),
        "Hero blink open-eye frame",
        crop_count=2,
        crop_index=0,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "hero-blink-sheet-source-v1.png",
        "hero-blink-frame-2-v1.png",
        (64, 64),
        (54, 48),
        "Hero blink closed-eye frame",
        crop_count=2,
        crop_index=1,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "hero-sleep-sheet-source-v1.png",
        "hero-sleep-frame-1-v1.png",
        (64, 64),
        (54, 48),
        "Hero sleeping frame 1",
        crop_count=2,
        crop_index=0,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "hero-sleep-sheet-source-v1.png",
        "hero-sleep-frame-2-v1.png",
        (64, 64),
        (54, 48),
        "Hero sleeping frame 2",
        crop_count=2,
        crop_index=1,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "hero-turn-sheet-source-v1.png",
        "hero-turn-frame-1-v1.png",
        (64, 64),
        (54, 48),
        "Hero direction-turn frame 1",
        crop_count=4,
        crop_index=0,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "hero-turn-sheet-source-v1.png",
        "hero-turn-frame-2-v1.png",
        (64, 64),
        (54, 48),
        "Hero direction-turn frame 2",
        crop_count=4,
        crop_index=1,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "hero-turn-sheet-source-v1.png",
        "hero-turn-frame-3-v1.png",
        (64, 64),
        (48, 50),
        "Hero direction-turn front frame",
        crop_count=4,
        crop_index=2,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "hero-turn-sheet-source-v1.png",
        "hero-turn-frame-4-v1.png",
        (64, 64),
        (54, 48),
        "Hero direction-turn frame 4",
        crop_count=4,
        crop_index=3,
        isolate_largest=True,
        align="bottom",
    ),
    AssetSpec(
        "state-controller-pairing-source-v1.png",
        "state-controller-pairing-160x112-v1.png",
        (160, 112),
        (118, 98),
        "Bluetooth or USB controller pairing state",
    ),
    AssetSpec(
        "state-controller-disconnected-source-v1.png",
        "state-controller-disconnected-160x112-v1.png",
        (160, 112),
        (118, 98),
        "Controller disconnected state",
    ),
    AssetSpec(
        "state-low-memory-source-v1.png",
        "state-low-memory-160x112-v1.png",
        (160, 112),
        (118, 92),
        "Low-memory warning state",
        background="checker",
    ),
    AssetSpec(
        "state-storage-full-source-v1.png",
        "state-storage-full-160x112-v1.png",
        (160, 112),
        (118, 92),
        "Storage almost full warning state",
        background="checker",
    ),
    AssetSpec(
        "state-camera-unavailable-source-v2.png",
        "state-camera-unavailable-160x112-v1.png",
        (160, 112),
        (124, 100),
        "Camera hardware unavailable state",
    ),
    AssetSpec(
        "fishing-water-surface-source-v1.png",
        "fishing-water-surface-480x80-v1.png",
        (480, 80),
        (480, 76),
        "Repeatable fishing water-surface overlay",
    ),
    AssetSpec(
        "fishing-bobber-sheet-source-v1.png",
        "fishing-bobber-frame-1-v1.png",
        (64, 64),
        (62, 48),
        "Fishing bobber idle frame",
        crop_count=4,
        crop_index=0,
    ),
    AssetSpec(
        "fishing-bobber-sheet-source-v1.png",
        "fishing-bobber-frame-2-v1.png",
        (64, 64),
        (62, 48),
        "Fishing bobber nibble frame",
        crop_count=4,
        crop_index=1,
    ),
    AssetSpec(
        "fishing-bobber-sheet-source-v1.png",
        "fishing-bobber-frame-3-v1.png",
        (64, 64),
        (62, 48),
        "Fishing bobber bite frame",
        crop_count=4,
        crop_index=2,
    ),
    AssetSpec(
        "fishing-bobber-sheet-source-v1.png",
        "fishing-bobber-frame-4-v1.png",
        (64, 64),
        (62, 48),
        "Fishing hook-success splash frame",
        crop_count=4,
        crop_index=3,
    ),
    AssetSpec(
        "fishing-catch-frame-source-v1.png",
        "fishing-catch-frame-180x128-v1.png",
        (180, 128),
        (152, 116),
        "Empty catch-result presentation frame",
        background="checker",
    ),
)


def _is_neutral_background(pixel: tuple[int, int, int, int]) -> bool:
    red, green, blue, _alpha = pixel
    return min(red, green, blue) >= 232 and max(red, green, blue) - min(red, green, blue) <= 15


def remove_edge_checkerboard(image: Image.Image) -> Image.Image:
    """Remove only near-white neutral pixels connected to an image edge."""

    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    visited = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def enqueue(x: int, y: int) -> None:
        index = y * width + x
        if visited[index] or not _is_neutral_background(pixels[x, y]):
            return
        visited[index] = 1
        queue.append((x, y))

    for x in range(width):
        enqueue(x, 0)
        enqueue(x, height - 1)
    for y in range(height):
        enqueue(0, y)
        enqueue(width - 1, y)

    while queue:
        x, y = queue.popleft()
        pixels[x, y] = (0, 0, 0, 0)
        if x:
            enqueue(x - 1, y)
        if x + 1 < width:
            enqueue(x + 1, y)
        if y:
            enqueue(x, y - 1)
        if y + 1 < height:
            enqueue(x, y + 1)

    return rgba


def harden_alpha(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A").point(lambda value: 255 if value >= 96 else 0)
    rgba.putalpha(alpha)
    return rgba


def keep_largest_component(image: Image.Image) -> Image.Image:
    """Keep the intended sprite and discard neighboring-sheet fragments."""

    rgba = image.copy()
    width, height = rgba.size
    alpha = rgba.getchannel("A")
    alpha_pixels = alpha.load()
    visited = bytearray(width * height)

    components: list[list[tuple[int, int]]] = []
    for start_y in range(height):
        for start_x in range(width):
            start_index = start_y * width + start_x
            if visited[start_index] or alpha_pixels[start_x, start_y] == 0:
                continue
            visited[start_index] = 1
            queue: deque[tuple[int, int]] = deque(((start_x, start_y),))
            component: list[tuple[int, int]] = []
            while queue:
                x, y = queue.popleft()
                component.append((x, y))
                for nx, ny in (
                    (x - 1, y - 1),
                    (x, y - 1),
                    (x + 1, y - 1),
                    (x - 1, y),
                    (x + 1, y),
                    (x - 1, y + 1),
                    (x, y + 1),
                    (x + 1, y + 1),
                ):
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    index = ny * width + nx
                    if visited[index] or alpha_pixels[nx, ny] == 0:
                        continue
                    visited[index] = 1
                    queue.append((nx, ny))
            components.append(component)
    if not components:
        return rgba
    largest = max(components, key=len)
    keep = set(largest)
    for y in range(height):
        for x in range(width):
            if alpha_pixels[x, y] and (x, y) not in keep:
                rgba.putpixel((x, y), (0, 0, 0, 0))
    return rgba


def crop_visible(image: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("asset contains no visible pixels")
    return image.crop(bbox)


def fit_asset(image: Image.Image, spec: AssetSpec) -> Image.Image:
    image = crop_visible(harden_alpha(image))
    scale = min(spec.fit[0] / image.width, spec.fit[1] / image.height)
    resized = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.NEAREST,
    )
    canvas = Image.new("RGBA", spec.size, (0, 0, 0, 0))
    x = (spec.size[0] - resized.width) // 2
    if spec.align == "bottom":
        y = spec.size[1] - resized.height - 4
    else:
        y = (spec.size[1] - resized.height) // 2
    canvas.alpha_composite(resized, (x, y))
    if spec.isolate_largest:
        canvas = keep_largest_component(canvas)
    return canvas


def load_source(spec: AssetSpec) -> Image.Image:
    image = Image.open(SOURCE_DIR / spec.source)
    if spec.crop_count is not None:
        left = round(image.width * spec.crop_index / spec.crop_count)
        right = round(image.width * (spec.crop_index + 1) / spec.crop_count)
        image = image.crop((left, 0, right, image.height))
    elif spec.crop_quarter is not None:
        left = round(image.width * spec.crop_quarter / 4)
        right = round(image.width * (spec.crop_quarter + 1) / 4)
        image = image.crop((left, 0, right, image.height))
    if spec.background == "checker":
        image = remove_edge_checkerboard(image)
    return image.convert("RGBA")


def draw_checker(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], cell: int = 8) -> None:
    left, top, right, bottom = box
    for y in range(top, bottom, cell):
        for x in range(left, right, cell):
            color = (238, 242, 246) if ((x - left) // cell + (y - top) // cell) % 2 == 0 else (215, 222, 230)
            draw.rectangle((x, y, min(x + cell - 1, right), min(y + cell - 1, bottom)), fill=color)


def build_contact_sheet(outputs: list[tuple[AssetSpec, Path]]) -> Path:
    cell_width, cell_height = 220, 190
    columns = 4
    rows = (len(outputs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), (31, 38, 56))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for index, (spec, path) in enumerate(outputs):
        column, row = index % columns, index // columns
        left, top = column * cell_width, row * cell_height
        preview_box = (left + 16, top + 14, left + cell_width - 16, top + 142)
        draw_checker(draw, preview_box)
        asset = Image.open(path).convert("RGBA")
        scale = min((preview_box[2] - preview_box[0] - 12) / asset.width, (preview_box[3] - preview_box[1] - 12) / asset.height)
        preview = asset.resize(
            (max(1, round(asset.width * scale)), max(1, round(asset.height * scale))),
            Image.Resampling.NEAREST,
        )
        x = preview_box[0] + (preview_box[2] - preview_box[0] - preview.width) // 2
        y = preview_box[1] + (preview_box[3] - preview_box[1] - preview.height) // 2
        sheet.paste(preview, (x, y), preview)
        draw.text((left + 16, top + 150), spec.output, fill=(236, 241, 247), font=font)
        mode = Image.open(path).mode
        draw.text((left + 16, top + 166), f"{spec.size[0]}x{spec.size[1]} {mode}", fill=(147, 166, 190), font=font)

    path = OUTPUT_DIR / "generated-assets-contact-sheet-v1.png"
    sheet.save(path)
    return path


def write_manifest(outputs: list[tuple[AssetSpec, Path]]) -> Path:
    path = SOURCE_DIR / "asset-manifest.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            (
                "asset_id",
                "file",
                "width",
                "height",
                "format",
                "alpha",
                "purpose",
                "theme_variant",
                "source_file",
                "source_method",
                "license_status",
                "review_status",
            )
        )
        for spec, output in outputs:
            with Image.open(output) as image:
                alpha = "binary 0/255" if "A" in image.getbands() else "none/opaque"
            theme = "shared/aquatic"
            for candidate in ("aquatic", "fish", "graphite", "cream"):
                if f"-{candidate}-" in output.name:
                    theme = candidate
                    break
            writer.writerow(
                (
                    output.stem,
                    output.relative_to(ROOT).as_posix(),
                    spec.size[0],
                    spec.size[1],
                    "PNG",
                    alpha,
                    spec.purpose,
                    theme,
                    f"art/generated/{spec.source}",
                    "OpenAI built-in image generation + deterministic normalization",
                    "project candidate; confirm release terms before distribution",
                    "candidate-needs-in-app-review",
                )
            )
    return path


def build_animation_strip() -> tuple[AssetSpec, Path]:
    frame_paths = [OUTPUT_DIR / f"hero-swim-frame-{index}-v1.png" for index in range(1, 5)]
    strip = Image.new("RGBA", (256, 64), (0, 0, 0, 0))
    for index, frame_path in enumerate(frame_paths):
        strip.alpha_composite(Image.open(frame_path).convert("RGBA"), (index * 64, 0))
    output = OUTPUT_DIR / "hero-swim-strip-256x64-v1.png"
    strip.save(output, optimize=True)
    return (
        AssetSpec(
            "hero-swim-sheet-source-v1.png",
            output.name,
            strip.size,
            strip.size,
            "Four-frame hero swim animation strip",
        ),
        output,
    )


def build_background() -> tuple[AssetSpec, Path]:
    source = Image.open(SOURCE_DIR / "aquarium-background-source-v1.png").convert("RGB")
    output = OUTPUT_DIR / "aquarium-background-480-v1.png"
    source.resize((480, 480), Image.Resampling.NEAREST).save(output, optimize=True)
    return (
        AssetSpec(
            "aquarium-background-source-v1.png",
            output.name,
            (480, 480),
            (480, 480),
            "Low-detail aquarium environment candidate",
        ),
        output,
    )


def _asset_record(source: str, output: Path, purpose: str) -> tuple[AssetSpec, Path]:
    with Image.open(output) as image:
        size = image.size
    return AssetSpec(source, output.name, size, size, purpose), output


def _save_full_canvas_layer(source_name: str, output_name: str, checker: bool) -> Path:
    source = Image.open(SOURCE_DIR / source_name)
    if checker:
        source = remove_edge_checkerboard(source)
    source = harden_alpha(source.convert("RGBA"))
    output = OUTPUT_DIR / output_name
    source.resize((480, 480), Image.Resampling.NEAREST).save(output, optimize=True)
    return output


THEME_FAR_COLORS: dict[str, tuple[str, str, str]] = {
    "fish": ("#10172E", "#24385D", "#88B5D0"),
    "graphite": ("#171922", "#414652", "#B7C0CB"),
    "cream": ("#6A5847", "#B99B76", "#F4E2BE"),
}


THEME_MARK_COLORS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "aquatic": ((35, 45, 116), (48, 194, 220)),
    "fish": ((30, 36, 86), (226, 92, 103)),
    "graphite": ((39, 42, 54), (172, 184, 205)),
    "cream": ((91, 67, 47), (225, 154, 70)),
}


def build_environment_layers() -> list[tuple[AssetSpec, Path]]:
    outputs: list[tuple[AssetSpec, Path]] = []
    far_source = Image.open(SOURCE_DIR / "aquarium-far-source-v1.png").convert("RGB")
    far_aquatic = far_source.resize((480, 480), Image.Resampling.NEAREST)
    far_path = OUTPUT_DIR / "aquarium-far-aquatic-480-v1.png"
    far_aquatic.save(far_path, optimize=True)
    outputs.append(_asset_record("aquarium-far-source-v1.png", far_path, "Aquatic theme far-water layer"))

    mid_path = _save_full_canvas_layer(
        "aquarium-mid-source-v1.png", "aquarium-mid-overlay-480-v1.png", checker=True
    )
    foreground_path = _save_full_canvas_layer(
        "aquarium-foreground-source-v1.png", "aquarium-foreground-overlay-480-v1.png", checker=True
    )
    outputs.append(_asset_record("aquarium-mid-source-v1.png", mid_path, "Shared water shimmer and bubble overlay"))
    outputs.append(
        _asset_record(
            "aquarium-foreground-source-v1.png",
            foreground_path,
            "Shared transparent seabed foreground",
        )
    )

    far_paths: dict[str, Path] = {"aquatic": far_path}
    gray = ImageOps.grayscale(far_aquatic)
    for theme, (black, mid, white) in THEME_FAR_COLORS.items():
        themed = ImageOps.colorize(gray, black=black, white=white, mid=mid, blackpoint=0, midpoint=128, whitepoint=255)
        path = OUTPUT_DIR / f"aquarium-far-{theme}-480-v1.png"
        themed.save(path, optimize=True)
        far_paths[theme] = path
        outputs.append(_asset_record("aquarium-far-source-v1.png", path, f"{theme.title()} theme far-water layer"))

    mid = Image.open(mid_path).convert("RGBA")
    foreground = Image.open(foreground_path).convert("RGBA")
    for theme, path in far_paths.items():
        composite = Image.open(path).convert("RGBA")
        composite.alpha_composite(mid)
        composite.alpha_composite(foreground)
        output = OUTPUT_DIR / f"aquarium-composite-{theme}-480-v1.png"
        composite.convert("RGB").save(output, optimize=True)
        outputs.append(_asset_record("aquarium-far-source-v1.png", output, f"{theme.title()} full aquarium preview plate"))
    return outputs


def _flat_brand_mark(size: int, base: tuple[int, int, int], accent: tuple[int, int, int]) -> Image.Image:
    source = crop_visible(harden_alpha(Image.open(SOURCE_DIR / "brand-fish-mark-source-v1.png").convert("RGBA")))
    scale = min((size - max(4, size // 8)) / source.width, (size - max(4, size // 8)) / source.height)
    resized = source.resize(
        (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
        Image.Resampling.NEAREST,
    )
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    flat = Image.new("RGBA", resized.size, (0, 0, 0, 0))
    src_pixels = resized.load()
    dst_pixels = flat.load()
    for y in range(resized.height):
        for x in range(resized.width):
            red, green, blue, alpha = src_pixels[x, y]
            if alpha < 96:
                continue
            use_accent = green - red > 25 and blue >= green - 35
            color = accent if use_accent else base
            dst_pixels[x, y] = (*color, 255)
    result.alpha_composite(flat, ((size - flat.width) // 2, (size - flat.height) // 2))
    return result


def build_brand_assets() -> list[tuple[AssetSpec, Path]]:
    outputs: list[tuple[AssetSpec, Path]] = []
    for theme, colors in THEME_MARK_COLORS.items():
        for size in (32, 64, 256):
            if size == 256 and theme != "aquatic":
                continue
            output = OUTPUT_DIR / f"brand-fish-mark-{theme}-{size}-v1.png"
            _flat_brand_mark(size, *colors).save(output, optimize=True)
            outputs.append(_asset_record("brand-fish-mark-source-v1.png", output, f"{theme.title()} Fish brand mark"))
    return outputs


def build_decorative_patterns() -> list[tuple[AssetSpec, Path]]:
    """Build low-density 48px theme tiles from one AI-generated water motif."""

    source = harden_alpha(
        Image.open(SOURCE_DIR / "pattern-water-current-source-v1.png").convert("RGBA")
    ).resize((48, 48), Image.Resampling.NEAREST)
    alpha = source.getchannel("A")
    gray = ImageOps.grayscale(source.convert("RGB"))
    outputs: list[tuple[AssetSpec, Path]] = []
    for theme, (base, accent) in THEME_MARK_COLORS.items():
        colored = ImageOps.colorize(gray, black=base, white=accent).convert("RGBA")
        colored.putalpha(alpha)
        output = OUTPUT_DIR / f"decorative-water-tile-{theme}-48-v1.png"
        colored.save(output, optimize=True)
        outputs.append(
            _asset_record(
                "pattern-water-current-source-v1.png",
                output,
                f"{theme.title()} low-opacity decorative water tile",
            )
        )
    return outputs


def build_action_strips() -> list[tuple[AssetSpec, Path]]:
    outputs: list[tuple[AssetSpec, Path]] = []
    groups = (
        ("hero-blink", 2, "Hero two-frame blink animation"),
        ("hero-sleep", 2, "Hero two-frame sleep animation"),
        ("hero-turn", 4, "Hero four-frame direction turn"),
        ("fishing-bobber", 4, "Fishing bobber and splash animation"),
    )
    for prefix, count, purpose in groups:
        strip = Image.new("RGBA", (64 * count, 64), (0, 0, 0, 0))
        for index in range(1, count + 1):
            frame = Image.open(OUTPUT_DIR / f"{prefix}-frame-{index}-v1.png").convert("RGBA")
            strip.alpha_composite(frame, ((index - 1) * 64, 0))
        output = OUTPUT_DIR / f"{prefix}-strip-{64 * count}x64-v1.png"
        strip.save(output, optimize=True)
        outputs.append(_asset_record(f"{prefix}-sheet-source-v1.png", output, purpose))
    return outputs


def _contain(image: Image.Image, box: tuple[int, int], max_size: tuple[int, int]) -> tuple[Image.Image, tuple[int, int]]:
    rgba = crop_visible(image.convert("RGBA"))
    scale = min(max_size[0] / rgba.width, max_size[1] / rgba.height)
    resized = rgba.resize(
        (max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale))), Image.Resampling.NEAREST
    )
    return resized, (box[0] - resized.width // 2, box[1] - resized.height // 2)


def build_composite_states() -> list[tuple[AssetSpec, Path]]:
    outputs: list[tuple[AssetSpec, Path]] = []
    controller = Image.open(OUTPUT_DIR / "state-controller-pairing-160x112-v1.png").convert("RGBA")
    storage = Image.open(OUTPUT_DIR / "state-storage-full-160x112-v1.png").convert("RGBA")
    platforms = {
        "gba": Image.open(OUTPUT_DIR / "gba-cartridge-96x128-v1.png").convert("RGBA"),
        "ps1": Image.open(OUTPUT_DIR / "ps1-disc-case-96x128-v1.png").convert("RGBA"),
    }
    for platform, art in platforms.items():
        canvas = Image.new("RGBA", (180, 128), (0, 0, 0, 0))
        platform_art, platform_pos = _contain(art, (52, 66), (68, 94))
        controller_art, controller_pos = _contain(controller, (125, 70), (88, 68))
        canvas.alpha_composite(platform_art, platform_pos)
        canvas.alpha_composite(controller_art, controller_pos)
        output = OUTPUT_DIR / f"state-game-launch-{platform}-180x128-v1.png"
        canvas.save(output, optimize=True)
        outputs.append(_asset_record("state-controller-pairing-source-v1.png", output, f"{platform.upper()} game launch state"))

    exit_canvas = Image.new("RGBA", (180, 128), (0, 0, 0, 0))
    controller_art, controller_pos = _contain(controller, (58, 68), (88, 68))
    storage_art, storage_pos = _contain(storage, (128, 69), (82, 72))
    exit_canvas.alpha_composite(controller_art, controller_pos)
    exit_canvas.alpha_composite(storage_art, storage_pos)
    exit_output = OUTPUT_DIR / "state-game-exit-save-180x128-v1.png"
    exit_canvas.save(exit_output, optimize=True)
    outputs.append(_asset_record("state-storage-full-source-v1.png", exit_output, "Game save-and-exit state"))
    return outputs


def build_boot_splashes() -> list[tuple[AssetSpec, Path]]:
    outputs: list[tuple[AssetSpec, Path]] = []
    mid = Image.open(OUTPUT_DIR / "aquarium-mid-overlay-480-v1.png").convert("RGBA")
    for theme in THEME_MARK_COLORS:
        far = Image.open(OUTPUT_DIR / f"aquarium-far-{theme}-480-v1.png").convert("RGBA")
        far.alpha_composite(mid)
        mark = Image.open(OUTPUT_DIR / f"brand-fish-mark-{theme}-256-v1.png").convert("RGBA") if theme == "aquatic" else _flat_brand_mark(256, *THEME_MARK_COLORS[theme])
        mark = mark.resize((144, 144), Image.Resampling.NEAREST)
        far.alpha_composite(mark, ((480 - 144) // 2, 156))
        output = OUTPUT_DIR / f"boot-splash-{theme}-480-v1.png"
        far.convert("RGB").save(output, optimize=True)
        outputs.append(_asset_record("brand-fish-mark-source-v1.png", output, f"{theme.title()} text-free boot splash"))
    return outputs


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs: list[tuple[AssetSpec, Path]] = []
    for spec in SPECS:
        output = OUTPUT_DIR / spec.output
        fit_asset(load_source(spec), spec).save(output, optimize=True)
        outputs.append((spec, output))
    outputs.append(build_animation_strip())
    outputs.append(build_background())
    outputs.extend(build_environment_layers())
    outputs.extend(build_brand_assets())
    outputs.extend(build_decorative_patterns())
    outputs.extend(build_action_strips())
    outputs.extend(build_composite_states())
    outputs.extend(build_boot_splashes())
    contact_sheet = build_contact_sheet(outputs)
    manifest = write_manifest(outputs)
    print(f"normalized {len(outputs)} assets")
    print(contact_sheet)
    print(manifest)


if __name__ == "__main__":
    main()
