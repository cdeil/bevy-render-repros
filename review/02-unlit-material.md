# Unlit materials under Solari: a narrow composition patch

Existing report: [Bevy #26083](https://github.com/bevyengine/bevy/issues/26083).
It is open and a maintainer has offered to add support. Do not open a duplicate.
This procedural scene was written independently; no issue example was copied.

The red cube is `StandardMaterial { unlit: true, .. }`, authored at sRGB
(128, 32, 32). A lit floor and 15,000 lux directional light expose accidental
lighting contamination as well as exposure scaling. Tonemapping and debanding
are disabled. Raster and explicit forward rendering are controls.

`patches/solari-unlit-color.patch` applies to Bevy v0.20.0
`b3bdd75becaffe9a16677cf5bae5bd6d198f052b`. It decodes the deferred unlit flag
and uses the G-buffer's authored-color/emissive channel at final composition,
without multiplying it by exposure. Both the ReSTIR and non-ReSTIR shading
paths are changed. The new boolean is a local shader value, not a GPU buffer ABI.
The patch leaves ray tracing, reservoir history and lighting calculations intact.
It does not optimize away ray work for unlit pixels.

On macOS, apply `solari-metal-dispatch-padding.patch` separately first so the
independent Metal dispatch-layout failure does not mask this test. That workaround
is not part of the proposed unlit patch.

## Reproduce

Build the path-dependent `bevy-patched` binary with the Metal workaround only,
then capture the original behavior:

```sh
cargo build --release --manifest-path bevy-patched/Cargo.toml
uv run --script run_unlit_matrix.py before --binary "$CARGO_TARGET_DIR/release/bevy-scene-patched-repro"
git -C ../bevy apply ../bevy-render-repros/patches/solari-unlit-color.patch
cargo build --release --manifest-path bevy-patched/Cargo.toml
uv run --script run_unlit_matrix.py after --binary "$CARGO_TARGET_DIR/release/bevy-scene-patched-repro"
```

The script asserts process success, a completed screenshot, a raster reference
with over 1,000 interior pixels, the original Solari failure, and at most one
8-bit channel level of error in all corrected and control cases. It checks
EV100 9.7, 3 and 0, with ReSTIR enabled and disabled. Saved masks use 15,363
interior cube pixels, excluding edges. These checks quantify color preservation,
not a subjective assessment of global lighting quality.

## Bounds and review questions

- No DLSS or other denoiser is used; post-denoising exact segmentation colors
  remain a separate problem. Keep label passes outside a visual denoiser.
- No transparency, alpha mask, textured/vertex-color material, fog or bloom
  coverage is claimed. RGB9E5 packing can introduce quantization for other colors.
- World-cache debug visualization intentionally overrides the normal color.
- Confirm maintainer expectations for unlit secondary-ray appearance and whether
  skipping reservoirs/rays is desirable before extending this narrow patch.
- Final upstream wording must be independently human-written under Bevy's policy.
  This owned repository is a review artifact, not a submission to Bevy.
