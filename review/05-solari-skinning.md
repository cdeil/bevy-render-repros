# Document Solari mesh and deformation limits

**Proposed Bevy documentation PR:** State the exact raytracing mesh requirements and distinguish skipped skinning from stale morph geometry.
This is a known feature limitation, tracked by [#20203](https://github.com/bevyengine/bevy/issues/20203) and [compute skinning #7502](https://github.com/bevyengine/bevy/issues/7502). [#23255](https://github.com/bevyengine/bevy/pull/23255) is closed and unmerged. Status checked 2026-10-10; no duplicate bug is proposed.

## Reproduce

An original two-joint prism bends by 0.8 radians. The matrix compares native skinning, a compatible bind-pose copy and a CPU-baked static pose, then isolates extra vertex attributes, morph targets and a translated entity. There are no external meshes or animations.

```sh
export CARGO_TARGET_DIR="${REPRO_DATA:-$HOME/data/bevy-render-repros}/cache/cargo-target"
cargo build --release --locked -p bevy-skinning-repro
uv run --script run_skinning_matrix.py --out /new/skinning-run
```

## Results

[Metal](../evidence/skinning-controls-mac/results.json) and [Vulkan](../evidence/skinning-controls-linux/results.json), **36 completed captures**:

| Geometry | Raster | Path tracer |
| --- | --- | --- |
| Native skinned mesh | bends | silently excluded by extra joint attributes |
| Compatible bind-pose copy | GPU skin bends | stale straight geometry |
| CPU-baked static pose | identical silhouette to GPU skin | bent silhouette IoU 0.98454; stale copy is 0.19696 |
| Unskinned mesh with extra COLOR attribute | visible | silently excluded |
| Compatible mesh with morph target | morphed silhouette | unmorphed base shape |
| Bind-pose copy on entity translated +1 on X | skin silhouette unchanged | ray copy shifts 116.5 px; IoU 0 |

![Actual Metal controls](../evidence/skinning-controls-mac/comparison.png)

The compatibility check requires exactly the four default position/normal/UV/tangent attributes and formats. Skinning adds incompatible joint attributes; morph weights are ignored even for compatible meshes. Static copies do not follow later deformation.

## Prepared change and limits

[Release documentation patch](../patches/solari-skinning-docs.patch) targets 0.20.0 (`b3bdd75`); [main variant](../patches/solari-skinning-docs-main.patch) targets `0e93c7a`, whose opt-in API changed. Both apply; runtime evidence targets 0.20.0. Metal validation is confirmed; Linux Khronos layers are unavailable. These are geometry checks, not unlit or animation-performance tests.

The baked fixture uses an identity mesh-entity transform. For a baked pose attached to a transformed skinned entity, positions must be local:
`inverse(entity GlobalTransform) * Σ wᵢ · jointᵢ GlobalTransform · inverseBindᵢ`, or use a separate unskinned entity. A shared bind-pose BLAS is not correct for differently posed instances.

A full compute skin cache remains future work: per-instance deformation and previous-frame geometry, render synchronization, skinning before BLAS updates, bounds/dispatch limits and morph support. This patch documents the current contract rather than implementing that feature.

Technical draft for review; [publication requirements](../PUBLICATION.md).
