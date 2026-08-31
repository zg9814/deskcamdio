# Fish UI AI raster asset batch v1

This folder contains the first AI-generated raster candidate batch for the
480×480 DeskCamdio/Fish interface.  The existing application assets are not
overwritten.  Review the contact sheet before promoting any candidate into
`src/deskcamdio/assets`.

## Generation mode

- Generator: Codex built-in OpenAI image generation (`imagegen` skill)
- Date: 2026-08-31
- Direction: **Pocket Aquarium OS** — calm blue-grey water, dark-indigo
  outlines, controlled coral accents, pixel-art world objects, and clean
  code-rendered UI chrome.
- The full reusable prompt cards are recorded in
  [`UI_ART_OPTIMIZATION_GUIDE.md`](../../UI_ART_OPTIMIZATION_GUIDE.md), sections
  6 and 7.

## Prompt locks used for the final candidates

All generated world assets used these shared locks:

> Premium production candidate raster art for a 480×480 Raspberry Pi UI;
> authentic hard-edged 16-bit pixel clusters; compact readable silhouette;
> dark-indigo outline; restrained calm aquatic palette; soft top-left light;
> no text, logos, trademarks, watermarks, SVG/vector look, photorealism, 3D,
> blur, mixed pixel sizes, or copyrighted character likeness.

Asset-specific prompts requested:

- one friendly left-facing blue hero fish and a four-frame subtle swim loop;
- one coherent four-object vegetation/shell family;
- gallery photo bubble, memo bottle, music record, and sleeping focus timer;
- original generic teal handheld cartridge and indigo optical-disc case;
- four left-facing fishing fish with common/uncommon/rare/legendary silhouettes;
- a low-detail aquarium environment with an open central UI safe zone.

## Files

- `*-source-v1.png`: original generator output; retained for traceability.
- `processed/*.png`: deterministic native-size candidates with real alpha,
  nearest-neighbour scaling, fixed padding, and isolated-sheet fragments removed.
- `processed/generated-assets-contact-sheet-v1.png`: visual review sheet.
- `asset-manifest.csv`: dimensions, purpose, transparency, source, license, and
  review state.
- `scripts/process_generated_art.py`: reproducible normalization and contact
  sheet builder.

## QA status

- 20 sprite/UI candidates are RGBA with binary alpha values (0 or 255).
- The 480×480 background candidate is intentionally opaque RGB.
- GBA and optical-disc placeholders are original generic shapes without brand
  names or console logos.
- The generated aquarium background has a higher seabed than the target brief;
  keep it as a candidate until it is reviewed in an actual UI screenshot.
- The swim strip is a candidate animation.  Frame 1 is rebuilt from the approved
  hero seed; frames 2–4 must still be checked at runtime for visible motion.

Before release, confirm the project's chosen distribution terms for generated
art and change each manifest row from `candidate-needs-in-app-review` only after
reviewing it inside the real application.
