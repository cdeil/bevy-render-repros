# /// script
# requires-python = ">=3.12"
# ///
"""Storage layout matrix: 12/16-byte vec3, 3-scalar struct and array<u32, 3>."""

import argparse
import json
import os
import resource
import signal
import subprocess
from pathlib import Path
from repro_run import MAC, fresh_root, metal_validation, sanitize

parser = argparse.ArgumentParser()
parser.add_argument(
    "--out", help="new folder (default: timestamped, outside the checkout)"
)
parser.add_argument(
    "--release-only", action="store_true", help="skip the wgpu-main binary"
)
args = parser.parse_args()
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
target = Path(os.environ["CARGO_TARGET_DIR"]) / "release"
out = fresh_root(args.out, "vec3")
cases = [
    ("uint12", [], True),
    ("uint16", ["--padded"], True),
    ("int12", ["--signed"], True),
    ("int16", ["--signed", "--padded"], True),
    ("float12", ["--float"], True),
    ("float16", ["--float", "--padded"], True),
    ("scalars12", ["--scalars"], True),
    ("array12", ["--array"], True),
    # The written words drive a real indirect dispatch of 1 * 2 * 3 workgroups.
    ("uint16-indirect", ["--padded", "--indirect"], True),
    ("scalars12-indirect", ["--scalars", "--indirect"], True),
    ("array12-indirect", ["--array", "--indirect"], True),
]
if MAC:
    # MTL_DEBUG_LAYER only exists on Metal; on Linux this row would repeat uint12.
    cases.append(("uint12-unvalidated", [], False))
binaries = ["wgpu-vec3-repro"] + ([] if args.release_only else ["wgpu-main-vec3-repro"])
records = []
for binary in binaries:
    for case, flags, validation in cases:
        result = subprocess.run(
            [str(target / binary), *flags],
            env={**os.environ, "MTL_DEBUG_LAYER": "1" if validation else "0"},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        log = sanitize(result.stdout + result.stderr, out)
        name = f"{binary}-{case}.txt"
        (out / name).write_text(log)
        # Only a top-level vec3 binding is translated to a 16-byte Metal argument.
        vector = not any(flag in flags for flag in ("--scalars", "--array"))
        expected_layout_failure = (
            MAC and validation and vector and "--padded" not in flags
        )
        layout_assertion = (
            "has space for 12 bytes, but argument has a length(16)" in log
        )
        validated = metal_validation(log)
        if MAC:
            assert validated == validation, name
        if expected_layout_failure:
            assert result.returncode == -signal.SIGABRT and layout_assertion, name
        else:
            assert result.returncode == 0 and "GPU readback verified" in log, name
            if "--indirect" in flags:
                assert "Indirect dispatch verified: 6 workgroups" in log, name
        record = {
            "binary": binary,
            "case": case,
            "metal_api_validation": validated,
            "expected_layout_failure": expected_layout_failure,
            "layout_assertion": layout_assertion,
            "process_returncode": result.returncode,
            "shell_exit": 128 - result.returncode
            if result.returncode < 0
            else result.returncode,
            "log": name,
            "readback_verified": "GPU readback verified" in log,
            "indirect_dispatch_verified": "Indirect dispatch verified: 6 workgroups"
            in log,
        }
        records.append(record)
        print(record, flush=True)
    # Standalone Naga translation with default MSL options and fake binding slots;
    # wgpu's runtime compile options differ, so these files are for inspection only.
    for case, flags in (
        ("uint", []),
        ("scalars", ["--scalars"]),
        ("array", ["--array"]),
    ):
        subprocess.run(
            [
                str(target / binary),
                *flags,
                "--msl",
                str(out / f"{binary}-{case}.metal"),
                "--translate-only",
            ],
            check=True,
        )
(out / "results.json").write_text(json.dumps(records, indent=2) + "\n")
