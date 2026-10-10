# Unlit materials under Solari: a narrow composition patch

Existing report: [Bevy #26083](https://github.com/bevyengine/bevy/issues/26083).
It is open and a maintainer has offered to add support. Do not open a duplicate.
This procedural scene was written independently; no issue example was copied.
All prose and patches here are technical drafts prepared with AI assistance and
are not submission text.

The red cube is `StandardMaterial { unlit: true, .. }`, authored at sRGB
(128, 32, 32) unless `--color` or `--texture` is given. A lit floor and a
15,000 lux directional light make lighting contamination visible; only the cube
carries the exposure test, because the raster floor is saturated at all tested
exposures. Tonemapping and debanding are disabled.

## Mechanism

For an unlit material, Bevy's deferred G-buffer stores a zero base color, puts
the authored color in the emissive channel and sets the unlit flag. Deferred and
forward raster output that color without exposure. Released Solari treats the
pixel as a black surface emitting the authored color: it multiplies it by
exposure and adds the black surface's specular response, which gives the neutral
(56, 56, 56) at EV100 9.7 and white at EV100 3 and 0.

`patches/solari-unlit-color.patch` applies to Bevy v0.20.0
`b3bdd75becaffe9a16677cf5bae5bd6d198f052b` and to inspected main
`0e93c7ab7d5ec016990dcb226ec544aee1636d70`. It decodes the deferred unlit flag
and outputs the G-buffer's emissive channel unscaled at final composition, in
both the ReSTIR and non-ReSTIR shading paths. The new boolean is a local shader
value, not a GPU buffer ABI. Ray tracing, reservoir history and lighting
calculations are unchanged, and ray work for unlit pixels is not skipped.

**Scope: primary visibility only.** The patch fixes what the camera sees
directly on an unlit surface. Secondary rays are not changed: scene materials
used for ray hits ignore `unlit`, so an unlit surface still reflects, occludes
and bleeds color like a lit diffuse surface, and the `Pathtracer` reference mode
ignores `unlit` entirely. A large unlit backdrop with `RaytracingMesh3d` would
therefore still block sun and sky in rays. Whether unlit backdrops should simply
omit `RaytracingMesh3d` is a maintainer question.

## Reproduce

No Bevy checkout is needed. `build_solari_variants.py` copies the released
`bevy_solari` 0.20.0 crate from Cargo's registry, applies the patch files and
builds the procedural scene against each copy. On macOS the dispatch change from
packet 1 is required, so both binaries include it; it does not affect these
colors. `evidence/unlit-controls-*/variants.json` lists the variants built on
each host; see [Provenance](#provenance) for what the recorded runs do not show.

```sh
export CARGO_TARGET_DIR="${REPRO_DATA:-$HOME/data/bevy-render-repros}/cache/cargo-target"
uv run --script build_solari_variants.py dispatch-struct struct-unlit --out /new/variants
uv run --script run_unlit_matrix.py \
  --before /new/variants/dispatch-struct/bin/bevy-scene-solari-dispatch-struct \
  --after /new/variants/struct-unlit/bin/bevy-scene-solari-struct-unlit \
  --out /new/unlit-run
```

New runs record each binary's file name, SHA-256 and embedded WGSL markers in
`results.json`, using the same check as `build_solari_variants.py`, and refuse a
pair unless only the "before" binary lacks the unlit marker and both agree on the
dispatch-struct marker. The padding fallback changes only Rust, so the markers
cannot tell it apart from no dispatch change.

Recorded runs are rechecked offline, without a GPU. `--verify-existing` reruns
every assertion below on the saved PNGs and logs, requires the recorded numbers
to reproduce exactly, only reads the run folder and writes its report to a new
folder. `test_offline_checks.py` also runs it on corrupted copies, which must fail:

```sh
uv run --script run_unlit_matrix.py --verify-existing evidence/unlit-controls-mac --out /new/verify-mac
uv run --script run_unlit_matrix.py --verify-existing evidence/unlit-controls-linux --out /new/verify-linux
uv run --script test_offline_checks.py
```

Solari reads the deferred G-buffer, so **deferred raster** is the exact reference.
Each stage captures, with the original and the patched binary:

| Group | Cases | Assertion on the patched Solari output |
| --- | --- | --- |
| Fixture color, EV100 9.7, 3, 0 | forward raster, deferred raster, Solari ReSTIR off/on | equals deferred raster exactly |
| Textured: nearest 2×2 checker in `base_color_texture` | same four, EV100 9.7 | equals deferred raster exactly |
| Saturated (255,4,4), (200,10,120), (250,250,1) | same four, EV100 9.7 | equals deferred raster exactly |
| Solari camera with forward materials, three EVs | bypass control | whole image within one level of forward raster, on at most 0.1 % of pixels |
| Same color as an ordinary lit material, ReSTIR off/on | lit regression | under 0.1 % of pixels differ by more than 2 levels from the original |

The original Solari output must differ from deferred raster (mean error over
one level) in every Solari case, and every raster and bypass image must be
bit-identical between the two binaries. Masks are the authored-color interior of
the forward raster image, eroded by two pixels to exclude edges (15,363 pixels).

**Forward cases bypass Solari.** A Solari camera with forward materials renders
like plain raster and the ReSTIR setting has no effect. On Metal the image is
identical at every exposure, and on Vulkan at EV100 3 and 0. On Vulkan at
EV100 9.7, 160 floor pixels (0.061 %, bottom-right corner, x 487–511,
y 499–511) are one level darker than raster (239 instead of 240 in each
channel), identically before and after the patch. One possible cause, inferred
from source only and not verified, is the `Hdr` intermediate that the Solari
camera requires and the sRGB raster camera does not use. The same bound, at most
one level on at most 0.1 % of pixels, applies on every host. The earlier
matrix's six "forward ReSTIR" captures were therefore raster duplicates, not
Solari tests; the new matrix keeps one bypass control per exposure and labels it
as such.

**Forward raster is not the contract.** Deferred raster differs from forward
raster by up to 4 levels for saturated colors because of the G-buffer's RGB9E5
packing; Solari inherits exactly the deferred values. That is pre-existing
deferred quantization, not a patch defect. The fixture color (128, 32, 32)
survives the packing within one level, which is why the original ±1 forward check
passed.

## Observed results, 2026-10-10

`evidence/unlit-controls-mac/` (Apple M5 Pro, Metal API validation confirmed from
the runtime log line in every run) and `evidence/unlit-controls-linux/`
(RTX 4060 Ti, Vulkan) each hold 70 captures. Both hosts pass every assertion,
rechecked offline with `--verify-existing`:

| Case | Original Solari vs deferred raster (max / mean) | Patched |
| --- | --- | --- |
| Fixture, EV100 9.7, ReSTIR off / on | 216 / 40.4, 177–178 / 40.4 | 0 |
| Fixture, EV100 3 and 0 | 223 / 190–191 (white) | 0 |
| Textured, ReSTIR off / on | 223 / 40.4, 177–178 / 40.4 | 0 |
| (255,4,4), (200,10,120), (250,250,1) | 194–243 / 86–150 | 0 (forward raster differs by 4, 3, 1) |

Bypass control against forward raster, whole image, both stages:

| Host | EV100 9.7 | EV100 3 | EV100 0 |
| --- | --- | --- | --- |
| Metal | identical | identical | identical |
| Vulkan | 160 pixels differ by 1 level | identical | identical |

Lit-material regression, fraction of pixels differing by more than 2 levels:

| Host | ReSTIR | Original vs patched | Same binary twice |
| --- | --- | --- | --- |
| Metal | off / on | 0.006 % / 0.033 % | 0.004–0.011 % / 0.023–0.034 % |
| Vulkan | off / on | 0.002 % / 0.009 % | 0.008–0.011 % / 0.0004–0.022 % |

The lit differences are within run-to-run noise. Images shared with the
original matrix (`evidence/unlit-mac/`, `evidence/unlit-linux/`, built with the
padding fallback) agree: raster and bypass images are byte-identical, patched
cube pixels match exactly, and the remaining differences are a few dozen noisy
lit pixels. Some logs of both the original and the new runs, before and after the
patch, contain an intermittent startup warning about an unresolved
`bevy_solari::scene::sampling` shader import; it appears with unpatched binaries
too and every affected run still passes.

## Provenance

The recorded `results.json` files predate binary fingerprints: they store the
cases and flags, not which binaries produced them, and no hash is reconstructed
for them now. Each folder's `variants.json` lists the variants built on that
host: four on Metal, including `padding-unlit`, and three on Vulkan. The
intended pair is `dispatch-struct` and `struct-unlit`, but these runs cannot
prove it. The original padding-based matrix gives the same patched cube pixels,
so the conclusion does not depend on the dispatch change used. Offline
verification reports the pair as unknown. Runs made with the current script
record it.

## Bounds and review questions

- No DLSS or other denoiser is used. DLSS-RR guide buffers for unlit pixels are
  unchanged and were not tested; post-denoising exact segmentation colors remain
  a separate problem. Keep label passes outside a visual denoiser.
- No transparency, alpha mask, vertex colors, lightmaps, emissive-plus-unlit, fog
  or bloom coverage is claimed.
- World-cache debug visualization intentionally overrides the normal color.
- Confirm maintainer expectations for unlit secondary-ray appearance and whether
  skipping reservoirs/rays for unlit pixels is desirable before extending this
  narrow patch. Runtime on current main was checked on Metal only, in an
  independent review, not over Vulkan.
- Final upstream wording, including the code comment, must be independently
  human-written under Bevy's policy. This owned repository is a review artifact,
  not a submission to Bevy.

## Original matrix

`evidence/unlit-mac/` and `evidence/unlit-linux/` keep the first before/after
matrix (padding fallback, forward-raster reference, ±1 tolerance). Its claims
remain valid for the fixture color: every corrected case had maximum channel
error 0 over 15,363 pixels on both hosts.
