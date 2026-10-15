# Bevy rendering reproducers

Small procedural examples for Bevy 0.20, wgpu and Apple MetalFX, with tested patches and actual GPU screenshots. Start with the five short reports: each gives the problem, reproduction command, proposed change, evidence and limits. All examples and reviewed changes are now on `main`; upstream submissions remain pending human review.

## Findings

| Report | Conclusion | Runner |
| --- | --- | --- |
| [Metal dispatch](review/01-metal-storage.md) | Struct fix; existing wgpu #5739 | `run_vec3_matrix.py`, `run_bevy_cases.py` |
| [Unlit color](review/02-unlit-material.md) | Primary-visibility composition fix; Bevy #26083 | `run_unlit_matrix.py` |
| [Capture readiness](review/03-capture-readiness.md) | Asset-order/readiness documentation | `run_capture_matrix.py` |
| [MetalFX](review/04-metalfx.md) | Native denoising proof; separate Bevy 0.20 upscaler port | `metalfx/run_native.py`, `run_plugin_matrix.py` |
| [Skinning](review/05-solari-skinning.md) | Known mesh/deformation limits; documentation | `run_skinning_matrix.py` |

The unlit comparison below shows forward raster, deferred raster, original Solari and patched Solari. The corrected camera-visible colors match deferred raster, including textures and saturated colors.

![Actual Metal unlit before/after captures](evidence/unlit-verified-mac/comparison.png)

The native MetalFX demo also tests history at an object teleport. Keeping history can improve whole-frame error while leaving a local ghost; the report distinguishes those effects. The separate upscaler port does not add live Solari denoising.

![Actual MetalFX history-reset diagnostic](evidence/metalfx-history/teleport-0016-crop.png)

## Quick start

Requires Rust 1.97.1+, Cargo, Python 3.12+ and [uv](https://docs.astral.sh/uv/). Recorded-image checks work without a GPU:

```sh
mkdir -p "$HOME/code/oss"
git clone https://github.com/cdeil/bevy-render-repros.git "$HOME/code/oss/bevy-render-repros"
cd "$HOME/code/oss/bevy-render-repros"
export REPRO_DATA="$HOME/data/bevy-render-repros"
uv run --script run_unlit_matrix.py --verify-existing evidence/unlit-verified-mac
uv run --script run_unlit_matrix.py --verify-existing evidence/unlit-verified-linux
uv run --script test_offline_checks.py
```

For new GPU captures, first build the procedural scenes and patched Solari variants:

```sh
export CARGO_TARGET_DIR="$REPRO_DATA/cache/cargo-target"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
cargo build --release --locked --workspace
uv run --script build_solari_variants.py --out "$REPRO_DATA/runs/$RUN_ID-variants"
uv run --script run_bevy_cases.py "$REPRO_DATA/runs/$RUN_ID-variants"
```

Each report supplies the remaining case-specific commands. Raytracing requires supported hardware; MetalFX execution requires a supported Mac/device/SDK. The optional MetalFX plugin consumer resolves the merged Bevy 0.20 port of `bevy_metalfx` from GitHub at a pinned commit; see the correction in its report about the content size those runs recorded.

## Evidence and scope

GPU runs use Apple M5 Pro/macOS 27.0.1 Metal and RTX 4060 Ti/Linux Vulkan. Metal API validation is confirmed from runtime logs; Vulkan checks use wgpu validation and completed readback, without Khronos API layers. Runtime matrices target released Bevy 0.20.0; patch applicability to inspected main is stated separately. No Windows coverage or broad performance/quality ranking is claimed.

Selected screenshots, logs and JSON in `evidence/` are immutable records. Binary hashes and shader markers identify the fresh unlit runs. Every runner creates a new output directory outside the checkout; binaries, caches and large raw data live under `$REPRO_DATA`. Logs replace local paths. Older evidence remains available for reference; the reports link the relevant current results.

## License

Original reproducer code is [MIT licensed](LICENSE). Bevy, wgpu and ushas offer MIT or Apache-2.0 licensing, so MIT permits reuse with the required notices retained. Prepared upstream contributions must follow the target project's contribution licensing terms; this repository's license does not replace upstream licenses or attribution. See [patch-context licenses](THIRD_PARTY_NOTICES.md) and the retained texts in `LICENSES/`.

## Review and publication

These reports, documentation patches and code comments are AI-assisted technical drafts, not text to submit to Bevy. Human code ownership, independently written Bevy prose and explicit publication approval remain required. See [publication requirements](PUBLICATION.md) and [patch-context licenses](THIRD_PARTY_NOTICES.md).

The owned review PRs have been merged into this repository. No issue, PR, comment or fork has been submitted to upstream projects.
