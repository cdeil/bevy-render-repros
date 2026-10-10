# Document embedded-asset ordering and capture readiness

**Proposed Bevy documentation PR:** Register embedded shaders before loading them; clarify what synchronous pipeline compilation guarantees.
This is integration guidance, not a new engine bug. Existing [#21600](https://github.com/bevyengine/bevy/issues/21600) and [#6747](https://github.com/bevyengine/bevy/issues/6747) already track startup/capture concerns (open on 2026-10-10).

`MaterialPlugin::build` can request a shader during plugin construction. Registering that embedded shader after its load fails does not retry the load in this fixture. The screenshot may complete successfully while containing only clear color.

**Prepared change:** [capture-readiness-docs.patch](../patches/capture-readiness-docs.patch) explains registration ordering and that pipeline compilation alone does not ensure asset/render-resource readiness. It also removes the unsupported “iOS” claim from the synchronous-setting docs based on the actual compilation `cfg`; iOS was not tested. macOS ignores that setting by design.

## Reproduce

```sh
export CARGO_TARGET_DIR="${REPRO_DATA:-$HOME/data/bevy-render-repros}/cache/cargo-target"
cargo build --release --locked -p bevy-capture-repro
uv run --script run_capture_matrix.py --out /new/capture-run
```

The original constant-red material compares early registration, adjacent registration and registration deliberately delayed until update 30, with synchronous compilation on/off. Screenshot requests occur at main-world updates 0, 5 and 100; these are request indices, not measured GPU capture frames.

## Results

[Metal](../evidence/capture-strict-mac/results.json) and [Vulkan](../evidence/capture-strict-linux/results.json) provide **36 completed screenshots** with three distinct states: unwritten, clear-only and marker present.

| Case, requests 0 / 5 / 100 | Metal | Vulkan |
| --- | --- | --- |
| Early/adjacent, synchronous | marker / marker / marker | marker / marker / marker |
| Early/adjacent, asynchronous | marker / marker / marker | unwritten / clear-only / marker |
| Forced late, synchronous | clear-only throughout | clear-only throughout |
| Forced late, asynchronous | clear-only throughout | unwritten / clear-only / clear-only |

Early registration produces 15,376 marker pixels in the mature capture. Forced late registration produces **100% clear color**, with `Path not found` in the log; an unwritten target cannot pass that assertion. Adjacent registration happened to work, so no scheduler race is claimed.

## Scope

For offline capture, wait for required assets and pipeline/render preparation, then verify expected geometry before exporting. A fixed delay or an empty pipeline queue alone is insufficient for assets that have not queued pipelines yet. This fixture does not provide a general readiness API or a guaranteed frame count.

The documentation patch applies to 0.20.0 and inspected main (`0e93c7a`); runtime evidence is 0.20.0. Metal validation is confirmed from runtime logs; Vulkan Khronos layers are unavailable. The observed Linux synchronous behavior is not a reproduction of every condition reported in #21600.

Technical draft for review; [publication requirements](../PUBLICATION.md).
