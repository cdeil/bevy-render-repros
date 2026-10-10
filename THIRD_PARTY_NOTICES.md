# Patch context licenses

Original repro programs were written for this repository. The proposed patches
contain upstream source as diff context and, for the ushas port, modified
upstream files:

- `patches/ushas-bevy-20.patch`: adapted from
  [mistakeknot/ushas@717a240038e9ee41ecec39591bed40f1240bd8eb](https://github.com/mistakeknot/ushas/tree/717a240038e9ee41ecec39591bed40f1240bd8eb).
  As its header states, it is a complete Bevy 0.20/wgpu 30 migration of the
  library, its tools and CI, with readback cleanup, MSRV 1.97.1 and strict
  modern Clippy. It modifies library sources under `src/`, the diagnostic tools
  under `tools/` with their manifests and `Cargo.lock` files, the CI workflow,
  `Cargo.toml`, `rust-toolchain.toml`, `CHANGELOG.md`, the READMEs and
  `scripts/verify-published.sh`; every path is named in the diff. Copyright (c)
  2026 General Systems Ventures. MIT license text:
  [LICENSES/ushas-MIT.txt](LICENSES/ushas-MIT.txt).
- Other `patches/solari-*.patch` and `patches/capture-readiness-docs.patch`:
  adapted diff context from [bevyengine/bevy@v0.20.0](https://github.com/bevyengine/bevy/tree/b3bdd75becaffe9a16677cf5bae5bd6d198f052b),
  relevant files named in each diff. Original changes add a dispatch-argument
  struct, fallback dispatch padding, unlit composition or asset/capture/skinning
  documentation. `build_solari_variants.py` copies the released `bevy_solari`
  crate from the local Cargo registry into a run folder outside this repository
  at build time; no copy of that crate is stored here.
  The `solari-skinning-docs-main.patch` variant instead uses inspected main
  `0e93c7ab7d5ec016990dcb226ec544aee1636d70`; its source paths are named in the diff. Upstream's MIT text has no
  copyright line. MIT license text: [LICENSES/bevy-MIT.txt](LICENSES/bevy-MIT.txt).

Both upstream projects offer MIT or Apache-2.0 licensing; these excerpts use MIT.
No upstream NOTICE file was present at the source checkout root.
