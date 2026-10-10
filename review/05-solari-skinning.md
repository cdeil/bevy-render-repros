# Solari skinning: known limitation and documentation proposal

Tracker review first: [Solari #20203](https://github.com/bevyengine/bevy/issues/20203)
lists skinned/morphed meshes, [#7502](https://github.com/bevyengine/bevy/issues/7502)
tracks compute skinning, and [PR #23255](https://github.com/bevyengine/bevy/pull/23255)
is closed and unmerged. Its discussion includes previous-frame data and dispatch
size limits. No duplicate bug report or upstream submission is proposed.

## Original procedural reproducer

A two-joint prism bends its upper vertices by 0.8 radians. No downloaded meshes,
models, animations or textures are used. Each run requests an offscreen screenshot
after 140 updates and requires completed readback after 200. Three mesh choices,
two poses and raster/path-tracer controls produce 12 images per host.

```bash
export CARGO_TARGET_DIR="${REPRO_DATA:-$HOME/data/bevy-render-repros}/cache/cargo-target"
cargo build --release --locked -p bevy-skinning-repro
uv run run_skinning_matrix.py
```

The path tracer requires supported hardware ray queries. Metal API validation is
enabled on macOS. Vulkan uses wgpu validation and readback; the tested Linux host
has no Khronos validation layers installed.

- **Native skinned mesh:** extra joint attributes fail the exact four-attribute
  compatibility check. Both poses have zero red pixels in the path tracer.
- **Separate compatible bind-pose copy:** raster skinning changes shape, but ray
  geometry remains straight. This is not a deformation update mechanism.
- **CPU-baked static pose:** ordinary four-attribute geometry matches GPU-skinned
  raster silhouettes exactly in raster. The bent path-traced silhouette has
  IoU 0.98454 with raster; the stale bind-pose ray silhouette has IoU 0.19696.

Both macOS Metal and Linux Vulkan produced these results (24 completed captures).
The baked control proves a static geometry route, not interactive skin-cache
performance or correctness of motion vectors across animation frames. Colors
serve only as a silhouette mask; this is not a path-tracer unlit-material test.

![Actual Metal captures](../evidence/skinning-mac/comparison.png)
![Actual Vulkan captures](../evidence/skinning-linux/comparison.png)

## Prepared small PR

`patches/solari-skinning-docs.patch` targets Bevy v0.20.0
`b3bdd75becaffe9a16677cf5bae5bd6d198f052b`; the `-main` variant targets inspected
main `0e93c7ab7d5ec016990dcb226ec544aee1636d70`.
The main revision changed the raytracing opt-in API but retains the exact attribute
restriction. Both patch applicability checks passed. Runtime evidence is against
released 0.20.0; current-main runtime was not tested for this fixture.

The proposed documentation says **exactly** four attributes and explicitly
explains unsupported skin/morph deformation and the limits of a separate static
pose mesh. It does not implement skinning or add noisy warnings for all assets
(which may never be used by a RaytracingMesh3d entity).

## Larger contribution, separately scoped

A compute skin-cache contribution would need per-instance deformed positions,
normals and tangents; pose history; render extraction/synchronization; skinning
before BLAS updates and ray tracing; correct previous-frame geometry without
invalidating double-buffered TLAS state; bounds and dispatch chunking; resizing
and lifetime handling; and optional morph support. First agree that contract with
maintainers, then submit original static/two-pose acceptance fixtures with an
incremental compute implementation. Reusing a shared mesh's bind-pose BLAS for
multiple differently posed instances is not a correct implementation.

This preparation deliberately leaves the full renderer feature unfinished.
Independent human ownership, code review and independently written Bevy public
prose are required before any eventual upstream PR.
