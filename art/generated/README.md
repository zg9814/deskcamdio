# Fish UI AI raster asset pack v2

This directory contains the complete AI-generated raster candidate pack for
the 480×480 DeskCamdio/Fish interface. It follows the **Pocket Aquarium OS**
direction: precise code-rendered UI chrome layered over calm, compact 16-bit
aquarium art.

The pack does not replace functional text, controls, focus rings, progress
indicators, or Tabler icons. Those remain code-rendered for legibility,
localization, theme tinting, and Raspberry Pi Zero 2 W memory efficiency.

## Delivery status

- 30 retained source images, including superseded v1/v2 candidates.
- 76 normalized production candidates listed in `asset-manifest.csv`.
- 63 RGBA assets with strictly binary alpha (0/255).
- 13 intentional opaque RGB backgrounds, composites, and boot plates.
- Four theme families: Aquatic, Fish, Graphite, and Cream.
- Automated manifest, dimension, blank-image, source-existence, and alpha QA:
  zero reported problems as of 2026-08-31.
- All 76 normalized PNGs are packaged under `src/deskcamdio/assets/art/`.
- Selected assets are wired into the real Pygame standby, launcher, camera,
  gallery, music, memo, GBA, PS1, settings, and fishing pages using lazy loading.
- The 480×480 headless simulator and wheel packaging tests pass; Raspberry Pi
  display/performance review remains the final promotion gate.

## Covered asset families

- Hero fish, two companion fish, four-frame swim, four-frame turn, blink, and
  sleep actions.
- Seaweed, broad-leaf plant, coral bush, clam, layered aquarium backgrounds,
  full aquarium preview plates, and low-opacity theme tiles.
- Gallery, memo, music, focus, camera unavailable, controller pairing,
  controller disconnected, low-memory, and storage-full states.
- Generic GBA cartridge and optical-disc cover art plus game launch and
  save-and-exit compositions. No console logos or copyrighted characters.
- Four catchable fish, fishing water surface, four bobber/hook frames, catch
  presentation frame, and assembled animation strip.
- Four theme brand marks and text-free 480×480 boot splash plates.

## Directory map

- `*-source-v*.png`: untouched image-generation output retained for provenance.
- `processed/*.png`: deterministic native-size deliverables with nearest-
  neighbour scaling and normalized transparency.
- `processed/generated-assets-contact-sheet-v1.png`: complete visual contact
  sheet for side-by-side review.
- `processed/simulator-pages-contact-sheet-v1.png`: real 480×480 application
  pages rendered by the headless Pygame simulator after integration.
- `asset-manifest.csv`: asset ID, file, dimensions, alpha, purpose, theme,
  exact source file, generation method, license status, and review state.
- `../../scripts/process_generated_art.py`: reproducible normalization,
  theme-variant, strip, composite, manifest, and contact-sheet builder.
- `../../scripts/qa_generated_art.py`: automated deliverable validator.

## Generation locks

All source generations used the common direction below, with subject-specific
composition and dimensions:

> Production candidate raster art for a 480×480 Raspberry Pi UI; authentic
> hard-edged 16-bit pixel clusters; compact readable silhouette; dark-indigo
> outline; restrained calm aquatic palette; soft top-left light; no text,
> trademarks, watermarks, SVG/vector look, photorealism, 3D, blur, mixed pixel
> sizes, or copyrighted character likeness.

The complete reusable prompt cards and page-level art direction are recorded
in `UI_ART_OPTIMIZATION_GUIDE.md` at the repository root.

## Rebuild and validate

Run with a Python environment containing Pillow:

```powershell
python scripts/process_generated_art.py
python scripts/qa_generated_art.py
```

All files remain `candidate-needs-in-app-review` until viewed inside actual
480×480 application screens and tested on Raspberry Pi Zero 2 W. Before a
public release, confirm the project's chosen distribution terms for generated
art and update the manifest review/license fields accordingly.
