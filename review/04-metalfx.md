# MetalFX denoising: functional native proof and bridge proposal

This is a feature/integration packet, not a bug report. Read-only searches found
no dedicated denoiser issue in Bevy or the plugin tracker on 2026-10-10. Bevy's
merged [Metal support PR #25123](https://github.com/bevyengine/bevy/pull/25123)
already identifies the missing denoiser and mentions MetalFX as a possible route.
Do not open a duplicate "Metal does not denoise" bug.
All prose here is a technical draft prepared with AI assistance, not submission text.

## What runs

`metalfx/generate_guides.py` creates original analytic spheres, thin rods and a
plane, with seeded multiplicative radiance noise of known expectation. It is
**not** a physical path-tracer. There are no downloaded scenes or textures.
Depth is reversed-Z, matrices are right-handed/column-major and roughness is
exported perceptually and squared by the adapter. Normals are written in world
space, but `world_to_view` is the identity, so this fixture cannot tell world
from view space; that convention is untested. The camera and geometry are static
within each segment, so motion and jitter are 0.

At frame 16 the sphere **teleports**; the camera does not move, so this is not a
camera cut. The replay resets history there as an explicit history-reset control.
That is not a proposed bridge policy: resets belong on camera cuts, resizes and
toggles, while object motion and disocclusion belong to motion vectors.

`metalfx/replay.swift` uses Apple's actual `MTLFXTemporalDenoisedScaler`, creates
textures with the API's requested usage, encodes Metal commands, waits for GPU
completion and asserts finite HDR readback. Each replay records its history
policy in `report.json`: the normal run, a `--reset-every-frame` control, and a
`--no-cut-reset` control that keeps history across the teleport.

`metalfx/analyze.py` verifies guide ranges/normals, raw-data identity and finite
outputs, and asserts:

- both reports describe the expected policy and 32 frames;
- Metal API validation from the runtime's `Metal API Validation Enabled` log line
  of each replay, not from the requested environment variable;
- at frames 0 and 16, output equals the reset control within 0.0002 linear HDR;
- history helps: coherent MSE is below reset-every-frame MSE on every other
  frame, and below 0.8 × reset MSE from the fourth frame after each reset;
- with the no-reset control, frames 0–15 are bit-identical to the normal run and
  frame 16 differs.

```sh
uv run --script metalfx/run_native.py --out /new/metalfx-run
```

`run_native.py` generates the guides, runs the three replays with
`MTL_DEBUG_LAYER=1`, stores their logs and writes the analysis to
`<run>/evidence/`. Every step refuses an existing output folder, so recorded
evidence is never overwritten; reviewed results are added to `evidence/` under a
new name by an explicit copy. macOS 26+ and a device supporting this API are
required. A supported SDK alone does not establish device support. Linux can
generate the fixture, but cannot execute Apple's MetalFX API.

## Measured diagnostic

Apple M5 Pro, macOS 27.0.1: **64 completed GPU frames** (32 coherent + 32 reset
control), Metal API validation enabled. First-frame and teleport-frame output
match the reset control within the asserted 0.0002 linear-HDR tolerance. Mean
linear MSE against this analytic fixture is 0.04307 raw, 0.0002451 coherent and
0.0004692 with reset every frame; coherent MSE is 0.33–0.55 × the reset control's
from the fourth frame after each reset (frame 15: 0.000201 versus 0.000483).
These are diagnostic fixture values, **not a vendor-quality ranking**.

A rerun with the strengthened analysis and the no-reset control
(`evidence/metalfx-history/`, 96 frames with validation confirmed from the logs)
reproduced every per-frame metric of `evidence/metalfx/` exactly. Whole-frame and
local error tell different stories at the teleport:

| Frame 16 | Reset at teleport | History kept |
| --- | --- | --- |
| Whole-frame MSE | 0.000474 | 0.000393 |
| MSE over the sphere's old and new positions (7,862 px) | 0.00119 | 0.00131 |

Keeping history lowers whole-frame error, because about 87 % of the frame is
unchanged and its history stays valid, but raises error where the sphere moved and
leaves a visible ghost of the old position
(`evidence/metalfx-history/teleport-0016-crop.png`). The reset equivalence proves
that the reset is honoured; it does not show that resetting on object motion is
better.

Initialization was 0.935 seconds. Median GPU command time including output
readback was 1.944 ms at 320×192; no complete-renderer speed claim is implied.
Swift typecheck and the Python assertions pass. PNGs use the same linear-to-sRGB
mapping for raw, denoised and reference, without a per-image exposure adjustment.

![Actual native output, frame 15](../evidence/metalfx/comparison-0015.png)
![Scene-cut reset output, frame 16](../evidence/metalfx/comparison-0016.png)

## Existing projects and useful next PR

- [bevy_metalfx / ushas](https://github.com/mistakeknot/ushas): released 0.4.2
  and current 0.5.0-rc.1 source still target Bevy 0.19 / wgpu 29. It implements
  upscaling and frame interpolation, not this denoising pass. Its Metal interop
  is useful reference; it is not a drop-in Solari denoiser.
- [mtl-fx](https://github.com/jasonherald/metal.rs): native Rust MetalFX bindings,
  not a Bevy renderer integration.
- [objc2-metal-fx](https://docs.rs/objc2-metal-fx/latest/objc2_metal_fx/): direct
  native bindings, including denoised scalers.

The useful first implementation PR would be **an optional Bevy 0.20 MetalFX
Solari denoiser plugin**, initially native resolution and no frame interpolation.
A safe bridge must:

1. Obtain Bevy/wgpu's Metal device, guide textures and encoding ownership without
   mixing unsafe native encoding with wgpu calls on the same live encoder.
2. Insert the pass after Solari shading and before tonemapping/presentation,
   reading the same frame's HDR color and guides; keep IDs outside the denoiser.
3. Convert/verify surface guides, depth direction, motion units/sign, normal space,
   roughness, camera matrices, jitter and exposure. Moving-camera/object tests are
   required: this zero-motion fixture does not validate those conventions.
4. Allocate outputs safely, preserve command ordering/lifetimes, handle resize,
   cuts, toggles and unsupported devices, and reset history once per discontinuity.
5. Compare passthrough/raw/denoised output with a moving procedural scene, with
   Metal validation and correct color-space handling, before making quality claims.

A live plugin is **not implemented** in this packet. The native API/data path is
proven; the Bevy/wgpu ownership, scheduling and guide conversion still require
engineering. Estimate several days for a first tested prototype, then further
review/coverage; this is an estimate, not measured implementation work.

Sources: [Apple API](https://developer.apple.com/documentation/metalfx/mtlfxtemporaldenoisedscalerdescriptor),
[WWDC25 session](https://developer.apple.com/videos/play/wwdc2025/211/),
[released plugin manifest](https://docs.rs/crate/bevy_metalfx/0.4.2/source/Cargo.toml).
No upstream implementation was copied into this example.

## Additional concrete migration patch

The native demo is separate from `patches/ushas-bevy-20.patch`, which ports the
existing upscaler plugin at `717a240038e9ee41ecec39591bed40f1240bd8eb` to Bevy 0.20.
Dependency bumps alone produced 24 library compilation errors. The patch updates
sub-app extraction labels/generics, queries `ResolvedCompositingSpace`, handles
fallible timestamp mapping, and migrates the existing GPU resolve test to the
new device/submission API. It raises the library MSRV to Bevy's 1.97.1.

```sh
git clone https://github.com/mistakeknot/ushas.git ../ushas
git -C ../ushas checkout 717a240038e9ee41ecec39591bed40f1240bd8eb
git -C ../ushas apply ../bevy-render-repros/patches/ushas-bevy-20.patch
cargo build --release --manifest-path metalfx-plugin/Cargo.toml
MTL_DEBUG_LAYER=1 "$CARGO_TARGET_DIR/release/metalfx-plugin-repro" spatial /absolute/new-spatial.png
MTL_DEBUG_LAYER=1 "$CARGO_TARGET_DIR/release/metalfx-plugin-repro" temporal /absolute/new-temporal.png
```

`metalfx-plugin` is an original offscreen 11-rod scene with no downloaded assets.
It waits for repeated **current-frame `OutputWritten` observations**, then also
verifies completed screenshot readback; configuration/encoded status alone is
not accepted as GPU output. Spatial and temporal upscaling both actually ran on
Metal under API validation, and differ from the same-scale disabled/bilinear
control. This does **not** add ray reconstruction or establish panel presentation.
The comparison is an output identity check, not an upscaler quality benchmark.

![Actual live plugin captures](../evidence/metalfx-plugin/comparison.png)

The plugin's 130 existing Mac library tests passed, including the explicitly
executed Metal resolve test. Its first migrated GPU test failed because the
new command-buffer finishing API requires an initialized ComputeTaskPool;
that test setup was corrected and the complete run passed. Initial diagnostics
are retained privately; this is a migration/setup issue, not a Bevy defect.

Reproduction driver: `uv run --script run_plugin_matrix.py --out /new/folder` after
building the standalone manifest; it records Metal validation from the runtime log line. On Linux it expects `UnsupportedPlatform`, captures the
fallback and never reports native MetalFX execution. The fixture generator also
ran on Linux; frame 15 SHA256 matches the Mac input exactly:
`bb81a5ff671cfb7cbd605edc4348c87273d8e0ddd1842caf88119d072b084a34`.

Mac Clippy passed with `-D warnings -A deprecated`: the exemption is for existing
Rust/glam deprecation warnings, not new migration diagnostics. It does not claim
an entirely warning-free upstream crate on Rust 1.99. Its default pinned 1.97.1
can be overridden with `RUSTUP_TOOLCHAIN=stable` for a current installed compiler.

Linux port coverage: **82 existing library tests passed** on Rust 1.98.1, release
build/check and Clippy completed, and all three procedural consumer modes completed
screenshot readback. Spatial/temporal report `UnsupportedPlatform`, with images
identical to the disabled control; no native execution is claimed. macOS and Linux
CI-style Clippy use the disclosed `-A deprecated` allowance.

## Correction-round port validation

The migration now includes the separate smoke, benchmark, timing-probe and
claude-model packages, their lockfiles, CI/MSRV1.97.1 and compatibility docs.
Successful mapped buffers are unmapped on every subsequent error path. Actual
Mac Rust1.97.1 CI checks passed: seven library feature sets, all-target Clippy,
doctests, both hardware tests, package/license checks and all four tool packages
(58 smoke, 69 benchmark, 4 timing-probe and 3 model tests), plus 35 Swift tests.
The upgrade-introduced glam warning and atomic deprecation are fixed. Equivalent
array chunk iterations also remove Rust1.99 tool Clippy failures; the 131 tests
of smoke/benchmark/timing-probe and their strict Clippy passed again on 1.99.
No deprecation exception is required. This is CPU/tool and bounded GPU evidence;
full interactive smoke/benchmark rendering, resize, moving camera and presentation
coverage remain outside this packet. The external frozen consumer still uses
Bevy0.19 and must itself migrate before its full compatibility trial can pass.
