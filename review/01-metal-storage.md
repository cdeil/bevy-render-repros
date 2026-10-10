# Metal storage vector layout: technical evidence

Disposition: **existing upstream issue**, not a new report.
Target: https://github.com/gfx-rs/wgpu/issues/5739.
Potential downstream change: Bevy's Solari dispatch-buffer allocation.

## Facts established independently

- On Apple M5 Pro, macOS 27.0.1 build 26A434, Metal API validation aborts a
  one-dispatch shader with top-level storage `vec3<u32>` and a 12-byte buffer.
- The same happens for `vec3<i32>` and `vec3<f32>`.
- A 16-byte allocation completes and returns the expected three values for all
  three types. The fourth word retains its initial canary in these runs.
- A three-scalar struct uses 12 bytes and also completes with correct readback.
- Both wgpu 30.0.1 and current upstream commit
  `14dd4e8f717cd8c4381908895495ea19ef924c35` show these results.
- Naga's emitted MSL takes `device metal::uint3&` for the unsigned case.
- With validation disabled, the 12-byte case completes and returns the expected
  values. This does not establish safe backend layout or fix the validation
  failure.

Actual output is in `evidence/vec3/results.json`, with individual logs and
emitted MSL. A newer macOS build is not necessary to explain the issue: #5739
already describes the same translation and error. This investigation used only
one physical Mac; do not claim multi-device confirmation from these new runs.

## Candidate issue-update material

Use the facts above as research notes for a human-written follow-up to #5739.
Include the tiny shader, exact command, current revision, assertion, and working
scalar-struct control. Avoid opening a duplicate or claiming a backend fix.
The current upstream build emits two pre-existing unfulfilled-lint-expectation
warnings in `wgpu-core/src/lock/ranked.rs`; they are unrelated to the runtime
assertion and were not modified.

## Candidate Bevy workaround

Solari allocates `size_of::<[u32; 3]>()` for its world-cache indirect dispatch
buffer and binds it as a top-level storage vector. A 16-byte allocation would
accommodate Metal's current translated argument while leaving the first three
words available for indirect dispatch. This is a downstream workaround for
#5739, not a replacement for a Naga translation fix.

The independent procedural Bevy test completed 160 raster updates and saved its
screenshot. Solari aborted in `compact_world_cache_write_active_cells` with
Metal validation enabled. Applying the allocation patch to Bevy tag `v0.20.0`
completed 160 Solari updates and saved a screenshot with validation enabled.
The exact source base is `b3bdd75` (full hash in the environment record).
Linux/Vulkan controls are being checked separately.

## Human review before any submission

Understand the allocation/ABI distinction, inspect the original code and logs,
choose whether a downstream workaround is desirable, and write the final public
description. Disclose AI coding assistance accurately. No upstream issue,
comment, fork, branch or PR has been published by this investigation.
