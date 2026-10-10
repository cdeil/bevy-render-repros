# Patch context licenses

Reproducer programs are original MIT code. Proposed patches include upstream diff context; each patch names its source paths and changes.

- Bevy patches: adapted from [bevyengine/bevy@v0.20.0](https://github.com/bevyengine/bevy/tree/b3bdd75becaffe9a16677cf5bae5bd6d198f052b), or the inspected-main revision identified in a patch header. Changes cover dispatch layout, unlit composition and integration documentation as present on this branch. Upstream MIT text has no copyright line; see [LICENSES/bevy-MIT.txt](LICENSES/bevy-MIT.txt). The variant builder copies the registry crate only into external build data, not into this repository.
- `patches/ushas-bevy-20.patch`: adapted from [mistakeknot/ushas@717a240038e9ee41ecec39591bed40f1240bd8eb](https://github.com/mistakeknot/ushas/tree/717a240038e9ee41ecec39591bed40f1240bd8eb). Complete Bevy 0.20/wgpu 30 migration of library sources, tool packages/manifests/locks, CI, compatibility documentation and verification scripts; the diff lists every path. Copyright (c) 2026 General Systems Ventures. See [LICENSES/ushas-MIT.txt](LICENSES/ushas-MIT.txt).

The upstream projects offer MIT or Apache-2.0 licensing; these excerpts use MIT. No upstream NOTICE file was present at either checkout root.
