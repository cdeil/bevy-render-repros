# Embedded shader registration and capture readiness

This packet classifies integration lessons, not a newly discovered engine bug.
All prose and the documentation patch are technical drafts prepared with AI
assistance; any Bevy submission needs independently human-written text.

## Tracker searches

Searches on 2026-10-10 found:

- [Bevy #21600](https://github.com/bevyengine/bevy/issues/21600), open since
  2025-10: "Unpredictable start of rendering". It reports transparent or
  unpredictable first frames when exporting animation frames offline with Bevy
  0.17.2, and says `synchronous_pipeline_compilation` stopped helping in 0.17 on
  macOS and Linux. It links #6747. This is the closest existing report, and a
  documentation PR from this packet should reference it.
- [#6747](https://github.com/bevyengine/bevy/issues/6747), open since 2022:
  shadow maps are not rendered on the first frame.
- [#24869](https://github.com/bevyengine/bevy/issues/24869) (render-once
  lifecycle), [#6267](https://github.com/bevyengine/bevy/issues/6267) (missing
  shader handling) and [#25215](https://github.com/bevyengine/bevy/issues/25215)
  (screenshot images without camera targets). Our fixture has a camera target and
  is not a reproduction of #25215.

No new issue should be filed for this packet. The Linux observations below are
relevant data for #21600 but come from a different setup: Bevy 0.20.0,
pipelined rendering disabled, `Screenshot::image` on an `Image` render target,
and screenshot requests at fixed main-world updates rather than a per-frame
export plugin. On that setup synchronous compilation did give a complete first
request on Vulkan, which partly contradicts the issue's report. Whether that
belongs in a comment on #21600, rather than only in a doc PR, is for the human
contributor to decide.

## Fixture

`capture-scene` is an original procedural cube and constant-red WESL material.
Registering its embedded shader before the material plugin works. Deliberately
waiting until update 30 to register it lets the plugin's earlier asset request
fail: the mature screenshot is entirely clear color, the log identifies
`Path not found`, and registering later does not retry the failed load in this
setup. This isolates the ordering contract without depending on a scheduler race.
`MaterialPlugin::build` starts the shader load during plugin construction.

The adjacent-late variant registers immediately after the material plugin, as an
application might do by accident. Its outcome is recorded without a pass/fail
requirement: the asset loader can race that registration. Passing this variant
on a machine does not establish that the order is safe; the race itself has not
been demonstrated.

## Proposed documentation change

`patches/capture-readiness-docs.patch` (applies to v0.20.0 and inspected main
`0e93c7ab7d5ec016990dcb226ec544aee1636d70`):

- In the `embedded_asset!` docs, after the loading example: call the macro before
  adding plugins or running systems that load the asset, because plugin
  construction can already start the load, and registering the embedded asset
  after a load of that path has failed does not retry the load.
- On `RenderPlugin::synchronous_pipeline_compilation`: the setting only controls
  pipeline compilation; assets must still load and render resources must be
  prepared before an offline capture is complete.
- The same doc comment says the setting has no effect on "macOS, Wasm, iOS". The
  `cfg` on `create_pipeline_task` covers `target_os = "macos"`, `wasm32` and
  `not(feature = "multi_threaded")`, not iOS, so the patch removes "iOS". This is
  from source inspection only; nothing was run on iOS.

Do not attribute a Mac correction to changing the synchronous flag: macOS ignores it.

## Run

```sh
cargo build --release --locked -p bevy-capture-repro
uv run --script run_capture_matrix.py --out /new/capture-run
```

Each of six cases requests screenshots at main-world updates 0, 5 and 100.
**These are request indices, not measured GPU capture-frame indices**: Bevy's
screenshot API completes asynchronously. Every request is classified as
*unwritten* (RGB all zero), *clear-only* (the pass ran without the marker) or
*marker*. Assertions:

- early registration: the mature frame contains only marker red and the clear
  color, with over 2,000 red pixels;
- forced-late registration: the mature frame is **100 % clear color** and the log
  contains `Path not found`. An unwritten target cannot pass this check.

Early and adjacent request states are recorded, not required. This small scene
may have all shaders ready before even the first screenshot completes. No
deterministic asynchronous-compilation bug or regression is claimed.

For an offline renderer, wait for the required assets and pipelines, let scene
extraction/preparation settle, and verify the expected label geometry before
starting a fixed-step capture. Fixed sleep or a global empty pipeline queue alone
is not a sufficient readiness contract for assets that have not queued pipelines
yet. This packet supplies a reproducible documentation example, not a general
readiness API or upstream test suite.

## Observed platform results

`evidence/capture-strict-mac/` and `evidence/capture-strict-linux/` (36
screenshots) reproduce the original red-pixel counts in `evidence/capture-mac/`
and `evidence/capture-linux/` exactly. Early registration has 15,376 red pixels in
the mature screenshot; forced late registration is entirely clear color with the
expected missing-path error on both platforms. Adjacent-late registration happened
to work in these runs.

| Case (requests 0 / 5 / 100) | Metal | Vulkan |
| --- | --- | --- |
| early-sync, adjacent-sync | marker / marker / marker | marker / marker / marker |
| early-async, adjacent-async | marker / marker / marker | unwritten / clear-only / marker |
| late-sync | clear-only throughout | clear-only throughout |
| late-async | clear-only throughout | unwritten / clear-only / clear-only |

On Vulkan the asynchronous first request was never written and the fifth ran the
pass before the material pipeline was ready; this two-stage startup is why the
guidance asks for label-geometry checks rather than only "no marker yet". On Metal
both settings behave the same, consistent with the ignored flag. This is measured
startup behavior, not a promised frame count for other scenes. Metal API
validation was confirmed from the runtime log line; Linux has no Khronos
validation layers installed.
