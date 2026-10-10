# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.4.6", "pillow==12.3.0"]
# ///
"""Compare native skin, a bind-pose copy, a CPU-baked pose and three controls.

Controls: an unskinned mesh with one extra attribute (excluded like a skin), a
compatible morphed mesh (traced in its base shape) and a bind-pose copy on a
translated skinned entity (skinning ignores that transform; the ray copy does not).
"""

import argparse
import json
import os
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from repro_run import fresh_root, require_validation, sanitize

parser = argparse.ArgumentParser()
parser.add_argument(
    "--out", help="new folder (default: timestamped, outside the checkout)"
)
args = parser.parse_args()
binary = Path(os.environ["CARGO_TARGET_DIR"]) / "release/bevy-skinning-repro"
out = fresh_root(args.out, "skinning")
cases = [
    (mode, angle) for mode in ("native", "bind-copy", "baked") for angle in (0, 0.8)
]
cases += [("extra-attr", 0), ("morph", 0.8), ("bind-copy-offset", 0)]
records = []
masks = {}


def iou(a, b):
    return float((a & b).sum() / (a | b).sum())


def centroid_x(mask):
    return float(np.nonzero(mask)[1].mean()) if mask.any() else None


for ray in (False, True):
    for mode, angle in cases:
        name = f"{mode}-{angle:g}-" + ("ray" if ray else "raster")
        output = out / f"{name}.png"
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
        log = sanitize(result.stdout + result.stderr, out)
        output.with_suffix(".txt").write_text(log)
        assert result.returncode == 0 and "Completed 200 updates" in log, log
        rgb = np.asarray(Image.open(output).convert("RGB"))
        mask = (rgb[..., 0] > 80) & (rgb[..., 1] < 80) & (rgb[..., 2] < 80)
        masks[(ray, mode, angle)] = mask
        record = {
            "case": name,
            "foreground_pixels": int(mask.sum()),
            "centroid_x": centroid_x(mask),
            "returncode": result.returncode,
            "metal_api_validation": require_validation(log),
        }
        if ray and mode in ("native", "extra-attr"):
            # Any attribute beyond the four required ones excludes the mesh.
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
    iou_value = iou(raster, ray)
    assert iou_value > 0.96, iou_value
    checks[f"baked_ray_vs_skinned_raster_iou_{angle:g}"] = iou_value
assert not np.array_equal(masks[(False, "native", 0)], masks[(False, "native", 0.8)])
# Bind-pose ray mesh stays unchanged while raster skin moves.
fixed = masks[(True, "bind-copy", 0)]
other = masks[(True, "bind-copy", 0.8)]
assert iou(fixed, other) > 0.99
moved = masks[(False, "native", 0.8)]
checks["bind_pose_ray_vs_moved_raster_iou"] = iou(fixed, moved)
assert checks["bind_pose_ray_vs_moved_raster_iou"] < 0.8, checks
# Morph targets: raster morphs exactly like the baked pose; rays keep the base shape.
morph_raster = masks[(False, "morph", 0.8)]
morph_ray = masks[(True, "morph", 0.8)]
assert np.array_equal(morph_raster, masks[(False, "baked", 0.8)])
checks["morph_ray_vs_unmorphed_raster_iou"] = iou(morph_ray, masks[(False, "baked", 0)])
checks["morph_ray_vs_morphed_raster_iou"] = iou(morph_ray, morph_raster)
assert checks["morph_ray_vs_unmorphed_raster_iou"] > 0.96, checks
assert checks["morph_ray_vs_morphed_raster_iou"] < 0.8, checks
# Translated skinned entity: raster ignores the entity transform, the ray copy follows it.
offset_raster = masks[(False, "bind-copy-offset", 0)]
offset_ray = masks[(True, "bind-copy-offset", 0)]
assert np.array_equal(offset_raster, masks[(False, "native", 0)])
checks["offset_ray_vs_raster_iou"] = iou(offset_ray, offset_raster)
checks["offset_centroid_shift_px"] = centroid_x(offset_ray) - centroid_x(offset_raster)
assert checks["offset_ray_vs_raster_iou"] < 0.1, checks
assert checks["offset_centroid_shift_px"] > 50, checks
canvas = Image.new("RGB", (384 * 4, 2 * 408), "white")
draw = ImageDraw.Draw(canvas)
for i, (name, label) in enumerate(
    [
        ("native-0.8-raster", "Raster skin"),
        ("native-0.8-ray", "Native mesh: ray exclusion"),
        ("bind-copy-0.8-ray", "Bind copy: unchanged pose"),
        ("baked-0.8-ray", "CPU-baked pose: rays"),
        ("morph-0.8-raster", "Morph target: raster"),
        ("morph-0.8-ray", "Morph target: rays, base shape"),
        ("extra-attr-0-ray", "Extra COLOR attribute: rays"),
        ("bind-copy-offset-0-ray", "Copy on entity at x=+1: rays"),
    ]
):
    x, y = 384 * (i % 4), 408 * (i // 4)
    canvas.paste(Image.open(out / f"{name}.png"), (x, y + 24))
    draw.text((x + 6, y + 6), label, fill="black")
canvas.save(out / "comparison.png")
(out / "results.json").write_text(
    json.dumps({"records": records, "checks": checks}, indent=2) + "\n"
)
print(checks)
