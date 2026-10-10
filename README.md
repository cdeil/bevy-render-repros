# Rendering reproducers

Original procedural Rust/Swift examples, small GPU captures and proposed patches for review. No upstream submission has been made. The numbered reports give the conclusion, reproduction command, patch, evidence and limits for each candidate.

| Candidate | Prepared contribution | Runner |
| --- | --- | --- |
| [Metal dispatch](review/01-metal-storage.md) | Struct fix; existing wgpu #5739 | `run_vec3_matrix.py`, `run_bevy_cases.py` |
| [Unlit color](review/02-unlit-material.md) | Primary-visibility composition fix; Bevy #26083 | `run_unlit_matrix.py` |
| [Capture readiness](review/03-capture-readiness.md) | Asset-order/readiness documentation | `run_capture_matrix.py` |

## Build and run

Rust 1.97.1+, Cargo and uv are required. Raytracing cases need supported hardware; MetalFX execution needs a supported Mac/device/SDK. Clone this repository under `~/code/oss/`; the optional MetalFX consumer expects a sibling `ushas` clone.

```sh
export REPRO_DATA="$HOME/data/bevy-render-repros"
export CARGO_TARGET_DIR="$REPRO_DATA/cache/cargo-target"
cargo build --release --locked --workspace
uv run --script build_solari_variants.py --out "$REPRO_DATA/runs/variants-new"
uv run --script run_bevy_cases.py "$REPRO_DATA/runs/variants-new" --out "$REPRO_DATA/runs/solari-new"
```

Each report supplies its specific command. Every runner requires a new output directory outside this checkout. Selected screenshots/logs/results in `evidence/` are immutable records; binaries and large raw data stay in the external data directory. Logs replace local paths. Metal validation is confirmed from runtime output; Linux records normal wgpu/readback coverage, without Khronos API layers. No Windows coverage is claimed.

## Review and publication

These reports, documentation patches and code comments are AI-assisted technical drafts, not text to submit to Bevy. Human code ownership, independently written Bevy prose and explicit publication approval remain required. See [publication requirements](PUBLICATION.md) and [patch-context licenses](THIRD_PARTY_NOTICES.md).

The owned review PRs form a stack; review each against its stated base. Historical evidence remains available in Git and older evidence folders; the reports link the relevant current results.
