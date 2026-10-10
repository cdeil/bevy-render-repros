# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.4.6", "pillow==12.3.0"]
# ///
"""Capture an exposure/ReSTIR matrix. Run before and after the shader patch."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument("stage", choices=("before", "after"))
parser.add_argument("--binary", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
platform = "mac" if sys.platform == "darwin" else "linux"
evidence = root / "evidence" / f"unlit-{platform}" / args.stage
evidence.mkdir(parents=True, exist_ok=True)
records = []
reference = None
mask = None
for mode, flags in (
    ("raster", ["--raster"]),
    ("solari", []),
    ("forward", ["--forward"]),
):
    for restir in (False,) if mode == "raster" else (False, True):
        for ev in (9.7, 3.0, 0.0):
            name = f"{mode}-restir{int(restir)}-ev{ev:g}"
            output = evidence / f"{name}.png"
            output.unlink(missing_ok=True)
            command = [
                args.binary,
                "--unlit",
                "--ev",
                str(ev),
                "--out",
                str(output),
                *flags,
            ]
            if restir:
                command.append("--restir")
            result = subprocess.run(
                command,
                env={**os.environ, "MTL_DEBUG_LAYER": "1"},
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            log = (result.stdout + result.stderr).replace(str(root), "$REPRO_REPO")
            (evidence / f"{name}.txt").write_text(log)
            assert result.returncode == 0 and output.is_file(), log
            rgb = np.asarray(Image.open(output).convert("RGB"))
            if reference is None:
                reference = rgb
                # Use the interior authored-color pixels, excluding all object edges.
                mask = np.all(rgb == [128, 32, 32], axis=2)
                for axis in (0, 1):
                    mask &= np.roll(mask, 2, axis) & np.roll(mask, -2, axis)
                assert int(mask.sum()) > 1000, (
                    "Raster reference failed to expose authored color"
                )
            pixels = rgb[mask].astype(int)
            error = np.abs(pixels - [128, 32, 32])
            record = {
                "case": name,
                "ev100": ev,
                "restir": restir,
                "mode": mode,
                "pixels": int(mask.sum()),
                "median_rgb": np.median(pixels, axis=0).tolist(),
                "max_channel_error": int(error.max()),
                "mean_channel_error": float(error.mean()),
                "returncode": result.returncode,
                "metal_api_validation": platform == "mac",
            }
            if mode != "solari" or args.stage == "after":
                assert record["max_channel_error"] <= 1, record
            else:
                assert record["mean_channel_error"] > 1, record
            records.append(record)
            print(record, flush=True)
(evidence / "results.json").write_text(json.dumps(records, indent=2) + "\n")
