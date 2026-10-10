# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.4.6", "pillow==12.3.0"]
# ///
"""Compare native skin, a bind-pose copy and a static CPU-baked pose."""

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parent
binary = Path(os.environ["CARGO_TARGET_DIR"]) / "release/bevy-skinning-repro"
host = "mac" if sys.platform == "darwin" else "linux"
evidence = root / "evidence" / f"skinning-{host}"
evidence.mkdir(parents=True, exist_ok=True)
records = []
masks = {}
for ray in (False, True):
    for mode in ("native", "bind-copy", "baked"):
        for angle in (0, 0.8):
            name = f"{mode}-{angle:g}-" + ("ray" if ray else "raster")
            output = evidence / f"{name}.png"
            output.unlink(missing_ok=True)
            command = [str(binary), mode, str(angle), str(output)]
            if ray:
                command.append("--ray")
            result = subprocess.run(
                command,
                env={**os.environ, "MTL_DEBUG_LAYER": "1"},
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            log = (result.stdout + result.stderr).replace(str(root), "$REPRO_REPO")
            output.with_suffix(".txt").write_text(log)
            assert result.returncode == 0 and "Completed 200 updates" in log, log
            rgb = np.asarray(Image.open(output).convert("RGB"))
            mask = (rgb[..., 0] > 80) & (rgb[..., 1] < 80) & (rgb[..., 2] < 80)
            masks[(ray, mode, angle)] = mask
            record = {
                "case": name,
                "foreground_pixels": int(mask.sum()),
                "returncode": result.returncode,
                "metal_api_validation": host == "mac",
            }
            if ray and mode == "native":
                assert record["foreground_pixels"] == 0, record
            else:
                assert record["foreground_pixels"] > 1000, record
            records.append(record)
            print(record, flush=True)
checks = {}
for angle in (0, 0.8):
    raster = masks[(False, "native", angle)]
    baked = masks[(False, "baked", angle)]
    assert np.array_equal(raster, baked), (
        "GPU skin and original CPU pose must match raster silhouettes"
    )
    ray = masks[(True, "baked", angle)]
    iou = float((raster & ray).sum() / (raster | ray).sum())
    assert iou > 0.96, iou
    checks[f"baked_ray_vs_skinned_raster_iou_{angle:g}"] = iou
assert not np.array_equal(masks[(False, "native", 0)], masks[(False, "native", 0.8)])
# Bind-pose ray mesh stays unchanged while raster skin moves.
fixed = masks[(True, "bind-copy", 0)]
other = masks[(True, "bind-copy", 0.8)]
assert float((fixed & other).sum() / (fixed | other).sum()) > 0.99
moved = masks[(False, "native", 0.8)]
checks["bind_pose_ray_vs_moved_raster_iou"] = float(
    (fixed & moved).sum() / (fixed | moved).sum()
)
assert checks["bind_pose_ray_vs_moved_raster_iou"] < 0.8, checks
canvas = Image.new("RGB", (384 * 4, 408), "white")
draw = ImageDraw.Draw(canvas)
for i, (name, label) in enumerate(
    [
        ("native-0.8-raster", "Raster skin"),
        ("native-0.8-ray", "Native mesh: ray exclusion"),
        ("bind-copy-0.8-ray", "Bind copy: unchanged pose"),
        ("baked-0.8-ray", "CPU-baked pose: rays"),
    ]
):
    canvas.paste(Image.open(evidence / f"{name}.png"), (384 * i, 24))
    draw.text((384 * i + 6, 6), label, fill="black")
canvas.save(evidence / "comparison.png")
(evidence / "results.json").write_text(
    json.dumps({"records": records, "checks": checks}, indent=2) + "\n"
)
print(checks)
