# Preserve unlit colors in Solari composition

**Proposed Bevy PR:** Respect the deferred unlit flag in Solari's final composition.
This addresses existing [Bevy #26083](https://github.com/bevyengine/bevy/issues/26083), still open on 2026-10-10; no duplicate issue is proposed.

A cube using `StandardMaterial { unlit: true, .. }` should match deferred raster regardless of exposure. Released Solari instead applies exposure and lighting: the authored `(128,32,32)` becomes approximately gray at EV100 9.7 and white at EV100 3 and 0.

**Fix:** [solari-unlit-color.patch](../patches/solari-unlit-color.patch) reads the deferred unlit flag and outputs the emissive channel without exposure in both ReSTIR modes. This matches Bevy's deferred encoding of unlit color; it changes primary visibility only.

## Reproduce

```sh
export CARGO_TARGET_DIR="${REPRO_DATA:-$HOME/data/bevy-render-repros}/cache/cargo-target"
uv run --script build_solari_variants.py dispatch-struct struct-unlit --out /new/variants
uv run --script run_unlit_matrix.py \
  --before /new/variants/dispatch-struct/bin/bevy-scene-solari-dispatch-struct \
  --after /new/variants/struct-unlit/bin/bevy-scene-solari-struct-unlit \
  --out /new/unlit-run
```

Both binaries include the dispatch fix needed on Metal. The runner verifies embedded WGSL markers, records binary SHA-256 and refuses binaries that change during capture. No external scene or texture is required.

## Results

Fresh runs contain **70 completed captures per host**, with exact producing-binary fingerprints: [Metal results](../evidence/unlit-verified-mac/results.json) and [Vulkan results](../evidence/unlit-verified-linux/results.json).

| Control | Result on both hosts |
| --- | --- |
| EV100 9.7 / 3 / 0, ReSTIR off/on | patched unlit interior equals deferred raster exactly |
| Textured checker and three saturated colors | exact deferred match; original differs |
| Lit-material regression | fewer than 0.1% of pixels differ by more than two levels, within measured repeat noise |
| Forward-material bypass | unchanged before/after; Metal equals raster; Vulkan EV9.7 has 160 floor pixels differing by one level (0.061%) |

The unlit mask contains 15,363 interior pixels and excludes edges. Deferred raster is the correct reference: RGB9E5 packing can differ from forward raster by up to four levels for saturated colors. Bypass controls do not exercise Solari. Metal API validation is confirmed from every runtime log; Linux has normal wgpu validation, without Khronos layers.

![Actual Metal before/after captures](../evidence/unlit-verified-mac/comparison.png)

Saved evidence can be checked without a GPU; 23 offline corruption/guard tests pass:

```sh
uv run --script run_unlit_matrix.py --verify-existing evidence/unlit-verified-mac --out /new/verify-mac
uv run --script run_unlit_matrix.py --verify-existing evidence/unlit-verified-linux --out /new/verify-linux
uv run --script test_offline_checks.py
```

## Limits

Secondary ray hits and the path tracer still treat unlit materials as lit; this is not full unlit support. DLSS guide handling, fog, transparency, alpha masks, vertex colors and bloom are outside coverage. Label passes should remain separate from visual denoisers. The patch applies to 0.20.0 and inspected main (`0e93c7a`); the complete paired matrix targets released 0.20.0. Older evidence folders remain historical records and are not the source of the fingerprints above.

Technical draft for review; [publication requirements](../PUBLICATION.md).
