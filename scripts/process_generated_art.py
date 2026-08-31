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

from PIL import Image, ImageDraw, ImageFont


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
    ),
    AssetSpec(
        "fishing-fish-family-source-v1.png",
        "fishing-uncommon-64x48-v1.png",
        (64, 48),
        (54, 42),
        "Fishing uncommon fish candidate",
        crop_quarter=1,
    ),
    AssetSpec(
        "fishing-fish-family-source-v1.png",
        "fishing-rare-64x48-v1.png",
        (64, 48),
        (58, 40),
        "Fishing rare fish candidate",
        crop_quarter=2,
    ),
    AssetSpec(
        "fishing-fish-family-source-v1.png",
        "fishing-legendary-64x48-v1.png",
        (64, 48),
        (56, 42),
        "Fishing legendary fish candidate",
        crop_quarter=3,
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
    if spec.crop_quarter is not None:
        canvas = keep_largest_component(canvas)
    return canvas


def load_source(spec: AssetSpec) -> Image.Image:
    image = Image.open(SOURCE_DIR / spec.source)
    if spec.crop_quarter is not None:
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
        draw.text((left + 16, top + 166), f"{spec.size[0]}x{spec.size[1]} RGBA", fill=(147, 166, 190), font=font)

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
                "source_method",
                "license_status",
                "review_status",
            )
        )
        for spec, output in outputs:
            writer.writerow(
                (
                    output.stem,
                    output.relative_to(ROOT).as_posix(),
                    spec.size[0],
                    spec.size[1],
                    "PNG",
                    "binary 0/255",
                    spec.purpose,
                    "shared/aquatic",
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


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs: list[tuple[AssetSpec, Path]] = []
    for spec in SPECS:
        output = OUTPUT_DIR / spec.output
        fit_asset(load_source(spec), spec).save(output, optimize=True)
        outputs.append((spec, output))
    outputs.append(build_animation_strip())
    outputs.append(build_background())
    contact_sheet = build_contact_sheet(outputs)
    manifest = write_manifest(outputs)
    print(f"normalized {len(outputs)} assets")
    print(contact_sheet)
    print(manifest)


if __name__ == "__main__":
    main()
