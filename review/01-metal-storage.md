# Metal storage vector layout: technical evidence

Disposition: **existing upstream issue**, not a new report.
Target: https://github.com/gfx-rs/wgpu/issues/5739.
Potential downstream change: Bevy's Solari dispatch-buffer binding.

All prose and patches here are technical drafts prepared with AI assistance.
They are not submission text; see [Human review before any submission](#human-review-before-any-submission).

## Facts established independently

- On Apple M5 Pro, macOS 27.0.1 build 26A434, Metal API validation aborts a
  one-dispatch shader with top-level storage `vec3<u32>` and a 12-byte buffer.
- The same happens for `vec3<i32>` and `vec3<f32>`.
- A 16-byte allocation completes and returns the expected three values for all
  three types. The fourth word retains its initial canary in these runs.
- A three-scalar struct and an `array<u32, 3>` both use 12 bytes and complete
  with correct readback under validation.
- Used as indirect dispatch arguments, the written words of the 12-byte struct,
  the 12-byte array and the 16-byte vector each drive exactly 1 × 2 × 3 = 6
  workgroups (`--indirect`, counted with an atomic in a second dispatch).
- Both wgpu 30.0.1 and current upstream commit
  `14dd4e8f717cd8c4381908895495ea19ef924c35` show these results.
- The standalone Naga translation in these files (default MSL options, fake
  binding slots, not wgpu's runtime compile options) takes `device metal::uint3&`
  for the unsigned vector case and `device type_1&` with `uint inner[3]` for the
  array. The runtime assertion, not the dump, establishes the 16-byte argument.
- With validation disabled, the 12-byte case completes and returns the expected
  values. This does not establish safe backend layout or fix the validation
  failure.

Original output is in `evidence/vec3/results.json`. The layout matrix with the
array and indirect cases is in `evidence/vec3-layouts-mac/` and
`evidence/vec3-layouts-linux/`; every case shared with the original run has the
same outcome. A newer macOS build is not necessary to explain the issue: #5739
already describes the same translation and error. This investigation used only
one physical Mac; do not claim multi-device confirmation from these new runs.

## Candidate issue-update material

Use the facts above as research notes for a human-written follow-up to #5739.
Include the tiny shader, exact command, current revision, assertion, and working
scalar-struct and array controls. Avoid opening a duplicate or claiming a
backend fix. The current upstream build emits two pre-existing
unfulfilled-lint-expectation warnings in `wgpu-core/src/lock/ranked.rs`; they are
unrelated to the runtime assertion and were not modified.

## Candidate Bevy change

Solari allocates `size_of::<[u32; 3]>()` for its world-cache indirect dispatch
buffer and binds it as a top-level storage `vec3<u32>` in
`world_cache_compact.wesl`. It is the only such binding in Bevy's Solari crate.

**Preferred:** `patches/solari-dispatch-indirect-args.patch` declares the binding
with the `DispatchIndirectArgs { x, y, z: u32 }` struct that Bevy's meshlet
shaders already use for indirect arguments. The allocation stays 12 bytes and
nothing depends on how Naga translates `vec3`. The patch applies unchanged to
v0.20.0 and to inspected main `0e93c7ab7d5ec016990dcb226ec544aee1636d70`.
Mention wgpu #5739 in a PR description rather than a code comment.

**Fallback only:** `patches/solari-metal-dispatch-padding.patch` keeps the `vec3`
binding and allocates 16 bytes, sized to Naga's current translation. The first
three words keep the indirect-dispatch layout and the binding has no minimum
size, so it is correct on every backend, but the extra word becomes dead weight
once #5739 is fixed. Offer it only if maintainers prefer not to touch WGSL.

`run_bevy_cases.py` (`evidence/solari-dispatch-mac/`, `-linux/`) runs raster,
released Solari and both changes, each Solari case with ReSTIR off and on:

| Case | Metal, validation enabled | Vulkan |
| --- | --- | --- |
| Raster | completes; image byte-identical to `evidence/solari/raster.png` | completes; identical to recorded |
| Released Solari, ReSTIR off/on | aborts in `compact_world_cache_write_active_cells`, 12/16-byte assertion | completes |
| Struct change, ReSTIR off/on | completes 160 updates, no assertion | completes |
| Padding fallback, ReSTIR off/on | completes 160 updates, no assertion | completes |

The Solari binaries are built by `build_solari_variants.py` from the released
`bevy_solari` 0.20.0 crate plus the patch files, without a Bevy checkout. Each
WGSL variant is checked for its embedded marker text. The padding fallback
changes only Rust, so markers can show only that it lacks the struct change; its
effect is shown by Metal completing where the released binary aborts. On Vulkan
the released binary completes too, so there is neither a behavioural proof nor a
defect to fix there. The variant lock file may differ from this repository's only
in the patched crate's source. These runs check completion and a non-blank
capture; packet 2 checks image content with struct-based binaries from the same
script (its recorded runs did not store the exact pair; see review/02).

The original allocation-patch run against a sibling Bevy checkout at tag
`v0.20.0` (`b3bdd75`) is recorded in `evidence/solari/` and `evidence/solari-linux/`.
Hardware for Linux: RTX 4060 Ti, driver 610.57.04, Rust 1.98.1. The Khronos Vulkan
validation layer is not installed on that machine; these are actual GPU readback
checks with normal wgpu validation, not a claim of Vulkan API-layer coverage.
`MTL_DEBUG_LAYER` has no effect on Linux, so Linux records report validation as
not applicable and the unvalidated row is only run on macOS.

The first Linux scene control exposed a mistake in this reproducer: it requested
storage usage even for the raster camera's sRGB main texture. Vulkan rejects
that usage. Storage usage is now added only to the HDR Solari camera. That
reproducer correction is separate from the proposed engine change.

Bevy Solari's four existing unit tests pass with the patches applied
(`evidence/solari/unit-tests.txt`). They are CPU-only allocator, TLAS and
light-index tests and do not exercise the changed WESL or buffer size, so they are
not evidence for this change. Shader validity comes only from the GPU runs above.

## Human review before any submission

Understand the binding/ABI distinction, inspect the original code and logs,
choose between the struct change and the allocation fallback, and write the
final public description. Under Bevy's AI policy, code comments and any prose
must be written independently by the human contributor; disclose AI coding
assistance accurately. No upstream issue, comment, fork, branch or PR has been
published by this investigation.
