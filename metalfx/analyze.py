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

parser = argparse.ArgumentParser()
parser.add_argument("guides", type=Path)
parser.add_argument("coherent", type=Path)
parser.add_argument("reset", type=Path)
parser.add_argument("evidence", type=Path)
args = parser.parse_args()
args.evidence.mkdir(parents=True, exist_ok=True)
report = json.loads((args.coherent / "report.json").read_text())
width, height = report["width"], report["height"]
assert report["frames"] == 32 and report["metal_api_validation"]


def pfm(path):
    with path.open("rb") as f:
        assert f.readline() == b"PF\n"
        assert f.readline().strip() == f"{width} {height}".encode()
        assert f.readline() == b"-1.0\n"
        values = np.frombuffer(f.read(), dtype="<f4").reshape(height, width, 3)[::-1]
    assert np.isfinite(values).all()
    return values


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
    reference = np.fromfile(args.guides / f"{stem}-reference.bin", dtype="<f4").reshape(
        height, width, 3
    )
    raw = pfm(args.coherent / f"{stem}-raw.pfm")
    clean = pfm(args.coherent / f"{stem}-metalfx.pfm")
    reset = pfm(args.reset / f"{stem}-metalfx.pfm")
    assert np.allclose(raw, guide[..., :3])
    record = {
        "frame": frame,
        "reset_history": frame in (0, 16),
        "raw_mse": float(np.mean((raw - reference) ** 2)),
        "coherent_mse": float(np.mean((clean - reference) ** 2)),
        "reset_mse": float(np.mean((reset - reference) ** 2)),
        "coherent_vs_reset_mae": float(np.mean(np.abs(clean - reset))),
    }
    # Explicit scene-cut reset must match a newly reset control at this frame.
    if frame in (0, 16):
        assert np.allclose(clean, reset, atol=2e-4), record
    records.append(record)
    if frame in (0, 15, 16, 31):
        canvas = Image.new("RGB", (width * 3, height + 24), "white")
        draw = ImageDraw.Draw(canvas)
        for i, (array, label) in enumerate(
            (
                (raw, "Seeded noisy input"),
                (clean, "Native MetalFX"),
                (reference, "Analytic reference"),
            )
        ):
            linear = np.clip(array, 0, 1)
            srgb = np.where(
                linear <= 0.0031308, 12.92 * linear, 1.055 * linear ** (1 / 2.4) - 0.055
            )
            pixels = (np.clip(srgb, 0, 1) * 255).round().astype("uint8")
            canvas.paste(Image.fromarray(pixels), (width * i, 24))
            draw.text((width * i + 6, 6), f"{label} / frame {frame}", fill="black")
        canvas.save(args.evidence / f"comparison-{stem}.png")
assert np.mean([r["coherent_mse"] for r in records]) < np.mean(
    [r["raw_mse"] for r in records]
)
assert records[15]["coherent_vs_reset_mae"] > 0
summary = {
    "scope": "Seeded analytic diagnostic; not a path-tracer or vendor-quality ranking",
    "records": records,
    "native_report": report,
}
(args.evidence / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
print(
    {
        "frames": 32,
        "guide_checks": "pass",
        "scene_cut_reset_equivalence": "pass",
        "raw_mse_mean": float(np.mean([r["raw_mse"] for r in records])),
        "coherent_mse_mean": float(np.mean([r["coherent_mse"] for r in records])),
        "history_changes_frame15": records[15]["coherent_vs_reset_mae"],
    }
)
