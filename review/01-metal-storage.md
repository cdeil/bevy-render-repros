# Solari dispatch arguments fail Metal validation

**Proposed Bevy PR:** Use a scalar dispatch-argument struct in Solari.
The underlying backend issue is already tracked in [wgpu #5739](https://github.com/gfx-rs/wgpu/issues/5739); no duplicate issue is proposed. Status checked 2026-10-10.

Solari allocates 12 bytes for three indirect-dispatch words but binds them as a top-level storage `vec3<u32>`. Metal validation expects a 16-byte vector argument and aborts in `compact_world_cache_write_active_cells`, before a screenshot can complete.

**Fix:** [solari-dispatch-indirect-args.patch](../patches/solari-dispatch-indirect-args.patch) uses a module-local `DispatchIndirectArgs { x, y, z: u32 }`, following Bevy's meshlet shaders. The allocation remains 12 bytes. [16-byte allocation](../patches/solari-metal-dispatch-padding.patch) is a fallback if maintainers prefer to retain the vector binding.

## Minimal reproduction

```sh
export CARGO_TARGET_DIR="${REPRO_DATA:-$HOME/data/bevy-render-repros}/cache/cargo-target"
cargo build --release --locked -p wgpu-vec3-repro
MTL_DEBUG_LAYER=1 "$CARGO_TARGET_DIR/release/wgpu-vec3-repro"
MTL_DEBUG_LAYER=1 "$CARGO_TARGET_DIR/release/wgpu-vec3-repro" --scalars --indirect
```

The first command aborts on the tested Metal device; the scalar control asserts correct readback and exactly six indirect workgroups. `--array --indirect` and `--padded --indirect` also pass. Signed and floating-point vectors reproduce the same layout failure.

For the actual Solari scene:

```sh
uv run --script build_solari_variants.py --out /new/variants
uv run --script run_bevy_cases.py /new/variants --out /new/solari-run
```

## Evidence and scope

| Case | macOS Metal, API validation | Linux Vulkan |
| --- | --- | --- |
| Top-level vec3, 12 bytes | aborts | correct readback |
| Scalar struct / array, 12 bytes | correct readback and indirect dispatch | same |
| Vector, 16 bytes | correct readback and indirect dispatch | same |
| Released Solari, ReSTIR off/on | aborts | captures complete |
| Struct fix / padding fallback, ReSTIR off/on | captures complete | captures complete |

Tests cover wgpu 30.0.1 and upstream `14dd4e8f717cd8c4381908895495ea19ef924c35`, Apple M5 Pro/macOS 27.0.1 and RTX 4060 Ti/Linux. [Layout logs](../evidence/vec3-layouts-mac/results.json), [Vulkan controls](../evidence/vec3-layouts-linux/results.json), and [Solari captures](../evidence/solari-dispatch-mac/results.json) contain commands, outcomes and validation records. Successful runs assert GPU output; disabling validation is not a fix.

Both Bevy patches apply to released 0.20.0 (`b3bdd75`) and inspected main (`0e93c7a`); engine runtime coverage targets 0.20.0. Four existing Solari CPU tests pass but do not exercise this shader change. Vulkan Khronos layers are unavailable; no Windows or multi-Mac coverage is claimed.

Technical draft for review; [publication requirements](../PUBLICATION.md).
