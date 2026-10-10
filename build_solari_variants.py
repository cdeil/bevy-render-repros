# /// script
# requires-python = ">=3.12"
# ///
"""Build bevy-scene binaries against patched copies of the released bevy_solari crate.

Each variant copies bevy_solari 0.20.0 from Cargo's registry, applies files from
`patches/` and builds the procedural scene with `[patch.crates-io]`. No Bevy
checkout is needed or modified. Binaries are copied into the new run folder so a
later build in a shared CARGO_TARGET_DIR cannot replace them.
"""

import argparse
import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

from repro_run import ROOT, SOLARI_MARKERS, binary_fingerprint, fresh_root

PATCHES = ROOT / "patches"
VARIANTS = {
    # Preferred packet 1 change and the fallback allocation-only change.
    "dispatch-struct": ["solari-dispatch-indirect-args.patch"],
    "dispatch-padding": ["solari-metal-dispatch-padding.patch"],
    # Packet 2 before/after pairs on top of the preferred dispatch change.
    "struct-unlit": ["solari-dispatch-indirect-args.patch", "solari-unlit-color.patch"],
    # Reproduces the originally recorded packet 2 binary.
    "padding-unlit": [
        "solari-metal-dispatch-padding.patch",
        "solari-unlit-color.patch",
    ],
}
DEFAULT = ["dispatch-struct", "dispatch-padding"]
if (PATCHES / "solari-unlit-color.patch").exists():
    DEFAULT.append("struct-unlit")

parser = argparse.ArgumentParser()
parser.add_argument("variants", nargs="*", default=DEFAULT, choices=sorted(VARIANTS))
parser.add_argument(
    "--out", help="new folder (default: timestamped, outside the checkout)"
)
args = parser.parse_args()
out = fresh_root(args.out, "solari-variants")
metadata = json.loads(
    subprocess.run(
        ["cargo", "metadata", "--format-version", "1", "--locked"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
)
(solari,) = [
    p
    for p in metadata["packages"]
    if p["name"] == "bevy_solari" and p["version"] == "0.20.0"
]
source = Path(solari["manifest_path"]).parent
scene = tomllib.loads((ROOT / "bevy-scene/Cargo.toml").read_text())
features = scene["dependencies"]["bevy"]["features"]
root_lock = tomllib.loads((ROOT / "Cargo.lock").read_text())["package"]
locked = {(p["name"], p["version"], p.get("source")) for p in root_lock}
target = Path(os.environ["CARGO_TARGET_DIR"]) / "release"
built = {}
for variant in args.variants:
    folder = out / variant
    # A unique crate folder name keeps Cargo's path-dependency hashes distinct.
    crate = folder / f"bevy_solari-{variant}"
    shutil.copytree(source, crate)
    subprocess.run(["git", "init", "-q"], cwd=crate, check=True)
    for patch in VARIANTS[variant]:
        subprocess.run(
            ["git", "apply", "-p3", str(PATCHES / patch)], cwd=crate, check=True
        )
    shutil.rmtree(crate / ".git")
    package = f"bevy-scene-solari-{variant}"
    (folder / "Cargo.toml").write_text(
        f"""[workspace]

[package]
name = "{package}"
version = "0.1.0"
edition = "2024"
publish = false

[[bin]]
name = "{package}"
path = {json.dumps(str(ROOT / "bevy-scene/src/main.rs"))}

[dependencies]
bevy = {{ version = "=0.20.0", default-features = false, features = {json.dumps(features)} }}

[patch.crates-io]
bevy_solari = {{ path = "bevy_solari-{variant}" }}
"""
    )
    shutil.copy(ROOT / "Cargo.lock", folder / "Cargo.lock")
    subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--offline",
            "--manifest-path",
            str(folder / "Cargo.toml"),
        ],
        check=True,
    )
    # Only the patched crate's source may differ from the repository lock file.
    variant_lock = tomllib.loads((folder / "Cargo.lock").read_text())["package"]
    drift = [
        p
        for p in variant_lock
        if p["name"] not in ("bevy_solari", package)
        and (p["name"], p["version"], p.get("source")) not in locked
    ]
    assert not drift, drift
    binary = folder / "bin" / package
    binary.parent.mkdir()
    shutil.copy2(target / package, binary)
    fingerprint = binary_fingerprint(binary)
    # WGSL patches must be present exactly as listed; a Rust-only patch has no marker.
    for patch, marker in SOLARI_MARKERS.items():
        assert fingerprint["markers"][marker] == (patch in VARIANTS[variant]), (
            variant,
            marker,
        )
    built[variant] = {
        "binary": str(binary.relative_to(out)),
        "patches": VARIANTS[variant],
        "sha256": fingerprint["sha256"],
        "markers": fingerprint["markers"],
    }
    print(variant, built[variant], flush=True)
(out / "variants.json").write_text(json.dumps(built, indent=2) + "\n")
