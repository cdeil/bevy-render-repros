# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.4.6", "pillow==12.3.0"]
# ///
"""Solari dispatch-buffer cases: raster, released Solari and both candidate changes."""

import argparse
import json
import os
import resource
import signal
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image
from repro_run import MAC, fresh_root, require_validation, sanitize

parser = argparse.ArgumentParser()
parser.add_argument(
    "variants", type=Path, help="folder written by build_solari_variants.py"
)
parser.add_argument(
    "--out", help="new folder (default: timestamped, outside the checkout)"
)
args = parser.parse_args()
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
built = json.loads((args.variants / "variants.json").read_text())
released = Path(os.environ["CARGO_TARGET_DIR"]) / "release/bevy-scene-repro"
out = fresh_root(args.out, "solari-dispatch")
cases = [("raster", released, ["--raster"])]
for restir in (False, True):
    suffix = "-restir" if restir else ""
    flags = ["--restir"] if restir else []
    cases += [
        (f"solari{suffix}", released, flags),
        # Preferred change: 12-byte DispatchIndirectArgs struct, unchanged allocation.
        (
            f"solari-struct{suffix}",
            args.variants / built["dispatch-struct"]["binary"],
            flags,
        ),
        # Fallback change: unchanged vec3 binding, 16-byte allocation.
        (
            f"solari-padded{suffix}",
            args.variants / built["dispatch-padding"]["binary"],
            flags,
        ),
    ]
records = []
for case, binary, flags in cases:
    output = out / f"{case}.png"
    result = subprocess.run(
        [str(binary), "--out", str(output), *flags],
        env={**os.environ, "MTL_DEBUG_LAYER": "1"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    log = sanitize(result.stdout + result.stderr, out)
    (out / f"{case}.txt").write_text(log)
    validation = require_validation(log)
    expected_layout_failure = MAC and case.startswith("solari") and binary == released
    if expected_layout_failure:
        assert result.returncode == -signal.SIGABRT, log
        assert "world_cache_active_cells_dispatch" in log and "length(16)" in log, log
        assert not output.exists()
    else:
        assert result.returncode == 0 and output.is_file(), log
        assert "160 updates completed" in log, log
        # Completion only; packet 2's matrix checks colors. Reject a blank capture.
        assert np.asarray(Image.open(output).convert("RGB")).std() > 1, case
    record = {
        "case": case,
        "binary": binary.name,
        "returncode": result.returncode,
        "shell_exit": 128 - result.returncode
        if result.returncode < 0
        else result.returncode,
        "screenshot": output.is_file(),
        "metal_api_validation": validation,
        "expected_layout_failure": expected_layout_failure,
    }
    records.append(record)
    print(record, flush=True)
(out / "results.json").write_text(json.dumps(records, indent=2) + "\n")
