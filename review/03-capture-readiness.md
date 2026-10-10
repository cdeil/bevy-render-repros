# Embedded shader registration and capture readiness

This packet classifies integration lessons, not a newly discovered engine bug.
Tracker searches on 2026-10-10 found [Bevy #24869](https://github.com/bevyengine/bevy/issues/24869)
(render-once lifecycle), [#6267](https://github.com/bevyengine/bevy/issues/6267)
(missing shader handling), and [#25215](https://github.com/bevyengine/bevy/issues/25215)
(screenshot images without camera targets). Our fixture has a camera target and
is not a reproduction of #25215. No new issue should be filed for this packet.

`capture-scene` is an original procedural cube and constant-red WESL material.
Registering its embedded shader before the material plugin works. Deliberately
waiting until update 30 to register it lets the plugin's earlier asset request
fail: the mature screenshot contains no cube, the log identifies `Path not found`,
and simply registering later does not reload the failed request in this setup.
This isolates the ordering contract without depending on a scheduler race.

The adjacent-late variant registers immediately after the material plugin, as an
application might do by accident. Its outcome is recorded without a pass/fail
requirement: the asset loader can race that registration. Passing this variant
on a machine does not establish that the order is safe.

The proposed **documentation PR**, `patches/capture-readiness-docs.patch`, adds:

- Register embedded assets before plugins/systems that load them; plugin
  construction can start an asset request, and late registration is not a retry.
- Synchronous pipeline compilation controls compilation, not asset loading or
  completion of render resource preparation.

Bevy v0.20.0 already documents that the synchronous setting has no effect on
macOS. Source `create_pipeline_task` confirms it ignores the flag there and
blocks on compilation. Do not attribute a Mac correction to changing this flag.

## Run

```sh
cargo build --release --locked -p bevy-capture-repro
uv run --script run_capture_matrix.py
```

Each of six cases requests screenshots at main-world updates 0, 5 and 100.
**These are request indices, not measured GPU capture-frame indices**: Bevy's
screenshot API completes asynchronously. The checks assert the completed mature
image and the expected asset error, not first-frame readiness or GPU timing.
Early/adjacent sync and async output are recorded; timing-dependent early blanks
are not required. This small scene may have all shaders ready before even the
first screenshot completes. No deterministic asynchronous-compilation bug or
regression is claimed.

For an offline renderer, wait for the required assets and pipelines, let scene
extraction/preparation settle, and verify expected label geometry before starting
a fixed-step capture. Fixed sleep or a global empty pipeline queue alone is not
a sufficient readiness contract for assets that have not queued pipelines yet.
This packet supplies a reproducible documentation example, not a general readiness
API or upstream test suite.

## Observed platform results

Six cases per host completed, producing 36 screenshots total. Early registration
has 15,376 red pixels in the mature screenshot; forced late registration has 0
and the expected missing-path error on both platforms. Adjacent-late registration
happened to work in these runs; the forced-delay case demonstrates why depending
on that outcome is unsafe.

On Vulkan, the asynchronous cases had **0 red pixels** at request updates 0 and
5, then 15,376 at update 100. Synchronous cases had 15,376 at each request.
On Metal, both settings had 15,376 throughout, consistent with the ignored flag.
This is measured startup behavior, not a promised frame count for other scenes.
Strict release Clippy passed on each platform. Metal API validation was enabled;
Linux has no Khronos validation layers installed.
