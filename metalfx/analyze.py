# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.4.6", "pillow==12.3.0"]
# ///
"""Check finite native output and measure the procedural fixture only."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

VALIDATION_LINE = "Metal API Validation Enabled"
RESETS = (0, 16)  # first frame and the frame-16 object teleport
parser = argparse.ArgumentParser()
parser.add_argument("guides", type=Path)
parser.add_argument("coherent", type=Path)
parser.add_argument("reset", type=Path, help="--reset-every-frame replay")
parser.add_argument("evidence", type=Path, help="new folder; never overwritten")
parser.add_argument("--coherent-log", type=Path, required=True)
parser.add_argument("--reset-log", type=Path, required=True)
parser.add_argument("--no-teleport-reset", type=Path, help="--no-cut-reset replay")
parser.add_argument("--no-teleport-reset-log", type=Path)
args = parser.parse_args()
args.evidence.mkdir(parents=True, exist_ok=False)
runs = {"coherent": (args.coherent, args.coherent_log, False, True)}
runs["reset"] = (args.reset, args.reset_log, True, True)
if args.no_teleport_reset:
    assert args.no_teleport_reset_log, "--no-teleport-reset-log is required"
    runs["no_teleport_reset"] = (
        args.no_teleport_reset,
        args.no_teleport_reset_log,
        False,
        False,
    )
reports = {}
for name, (folder, log, every_frame, teleport_reset) in runs.items():
    report = json.loads((folder / "report.json").read_text())
    assert report["frames"] == 32, name
    # Each replay must describe its own history policy.
    assert report["reset_every_frame"] == every_frame, name
    assert report["teleport_reset"] == teleport_reset, name
    # Validation comes from the Metal runtime's log line, not the requested variable.
    assert VALIDATION_LINE in log.read_text(), f"{name}: no '{VALIDATION_LINE}'"
    report["metal_api_validation"] = True
    reports[name] = report
width, height = reports["coherent"]["width"], reports["coherent"]["height"]


def pfm(path):
    with path.open("rb") as f:
        assert f.readline() == b"PF\n"
        assert f.readline().strip() == f"{width} {height}".encode()
        assert f.readline() == b"-1.0\n"
        values = np.frombuffer(f.read(), dtype="<f4").reshape(height, width, 3)[::-1]
    assert np.isfinite(values).all()
    return values


def srgb8(array):
    linear = np.clip(array, 0, 1)
    srgb = np.where(
        linear <= 0.0031308, 12.92 * linear, 1.055 * linear ** (1 / 2.4) - 0.055
    )
    return (np.clip(srgb, 0, 1) * 255).round().astype("uint8")


def reference(frame):
    path = args.guides / f"{frame:04d}-reference.bin"
    return np.fromfile(path, dtype="<f4").reshape(height, width, 3)


records = []
for frame in range(32):
    stem = f"{frame:04d}"
    guide = np.fromfile(args.guides / f"{stem}.bin", dtype="<f4").reshape(
        height, width, 24
    )
    assert np.isfinite(guide).all()
    assert ((guide[..., 4] >= 0) & (guide[..., 4] <= 1)).all()
    hits = guide[..., 4] > 0
    assert np.allclose(np.linalg.norm(guide[..., 20:23][hits], axis=1), 1, atol=1e-5)
    truth = reference(frame)
    raw = pfm(args.coherent / f"{stem}-raw.pfm")
    clean = pfm(args.coherent / f"{stem}-metalfx.pfm")
    reset = pfm(args.reset / f"{stem}-metalfx.pfm")
    assert np.allclose(raw, guide[..., :3])
    record = {
        "frame": frame,
        "reset_history": frame in RESETS,
        "raw_mse": float(np.mean((raw - truth) ** 2)),
        "coherent_mse": float(np.mean((clean - truth) ** 2)),
        "reset_mse": float(np.mean((reset - truth) ** 2)),
        "coherent_vs_reset_mae": float(np.mean(np.abs(clean - reset))),
    }
    if frame in RESETS:
        # An explicit reset must match a newly reset control at this frame.
        assert np.allclose(clean, reset, atol=2e-4), record
    else:
        # History must help on every frame after a reset, not merely change output.
        assert record["coherent_mse"] < record["reset_mse"], record
        if frame % 16 >= 4:
            assert record["coherent_mse"] < 0.8 * record["reset_mse"], record
    records.append(record)
    if frame in (0, 15, 16, 31):
        canvas = Image.new("RGB", (width * 3, height + 24), "white")
        draw = ImageDraw.Draw(canvas)
        for i, (array, label) in enumerate(
            (
                (raw, "Seeded noisy input"),
                (clean, "Native MetalFX"),
                (truth, "Analytic reference"),
            )
        ):
            canvas.paste(Image.fromarray(srgb8(array)), (width * i, 24))
            draw.text((width * i + 6, 6), f"{label} / frame {frame}", fill="black")
        canvas.save(args.evidence / f"comparison-{stem}.png")
assert np.mean([r["coherent_mse"] for r in records]) < np.mean(
    [r["raw_mse"] for r in records]
)

teleport = None
if args.no_teleport_reset:
    # The teleported sphere's old and new positions; the rest of the frame is unchanged.
    changed = np.abs(reference(16) - reference(15)).sum(axis=2) > 0.05
    teleport = {"changed_pixels": int(changed.sum()), "frames": {}}
    for frame in range(32):
        stem = f"{frame:04d}"
        kept = pfm(args.no_teleport_reset / f"{stem}-metalfx.pfm")
        clean = pfm(args.coherent / f"{stem}-metalfx.pfm")
        if frame < 16:
            # Identical inputs and history up to the teleport.
            assert np.array_equal(kept, clean), frame
            continue
        truth = reference(frame)
        teleport["frames"][frame] = {
            "global_mse_with_reset": float(np.mean((clean - truth) ** 2)),
            "global_mse_history_kept": float(np.mean((kept - truth) ** 2)),
            "changed_region_mse_with_reset": float(
                np.mean(((clean - truth) ** 2)[changed])
            ),
            "changed_region_mse_history_kept": float(
                np.mean(((kept - truth) ** 2)[changed])
            ),
        }
    assert not np.array_equal(
        pfm(args.no_teleport_reset / "0016-metalfx.pfm"),
        pfm(args.coherent / "0016-metalfx.pfm"),
    ), "keeping history across the teleport must change frame 16"
    # Crop around the changed region: stale history leaves a ghost of the old position.
    rows, cols = np.nonzero(changed)
    top, bottom = max(rows.min() - 8, 0), min(rows.max() + 9, height)
    left, right = max(cols.min() - 8, 0), min(cols.max() + 9, width)
    crops = [
        (pfm(args.coherent / "0016-metalfx.pfm"), "Reset at teleport"),
        (pfm(args.no_teleport_reset / "0016-metalfx.pfm"), "History kept"),
        (reference(16), "Analytic reference"),
    ]
    tile_w, tile_h = 2 * (right - left), 2 * (bottom - top)
    canvas = Image.new("RGB", (tile_w * 3, tile_h + 24), "white")
    draw = ImageDraw.Draw(canvas)
    for i, (array, label) in enumerate(crops):
        tile = Image.fromarray(srgb8(array[top:bottom, left:right]))
        canvas.paste(tile.resize((tile_w, tile_h), Image.NEAREST), (tile_w * i, 24))
        draw.text((tile_w * i + 6, 6), f"{label} / frame 16 crop", fill="black")
    canvas.save(args.evidence / "teleport-0016-crop.png")
    teleport["crop_box"] = [int(left), int(top), int(right), int(bottom)]

summary = {
    "scope": "Seeded analytic diagnostic; not a path-tracer or vendor-quality ranking",
    "records": records,
    "native_reports": reports,
    "teleport_history_control": teleport,
}
(args.evidence / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
print(
    {
        "frames": 32,
        "guide_checks": "pass",
        "reset_equivalence_frames_0_16": "pass",
        "history_beats_reset_every_frame": "pass",
        "raw_mse_mean": float(np.mean([r["raw_mse"] for r in records])),
        "coherent_mse_mean": float(np.mean([r["coherent_mse"] for r in records])),
        "reset_mse_mean": float(np.mean([r["reset_mse"] for r in records])),
        "teleport_frame16": teleport and teleport["frames"][16],
    }
)
