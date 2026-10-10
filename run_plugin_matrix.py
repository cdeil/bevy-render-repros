# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.4.6", "pillow==12.3.0"]
# ///
"""Actual output checks for the prepared Bevy 0.20 upscaler port."""

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parent
binary = Path(os.environ["CARGO_TARGET_DIR"]) / "release/metalfx-plugin-repro"
mac = sys.platform == "darwin"
evidence = root / "evidence" / ("metalfx-plugin" if mac else "metalfx-plugin-linux")
evidence.mkdir(parents=True, exist_ok=True)
images = {}
records = {}
for mode in ("disabled", "spatial", "temporal"):
    output = evidence / f"{mode}.png"
    output.unlink(missing_ok=True)
    command = [str(binary), mode, str(output)]
    if not mac and mode != "disabled":
        command.append("--expect-unavailable")
    result = subprocess.run(
        command,
        env={**os.environ, "MTL_DEBUG_LAYER": "1"},
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    log = (result.stdout + result.stderr).replace(str(root), "$REPRO_REPO")
    output.with_suffix(".txt").write_text(log)
    assert result.returncode == 0 and "Completed screenshot readback" in log, log
    if mode != "disabled":
        assert ("state: OutputWritten" if mac else "UnsupportedPlatform") in log, log
    rgb = np.asarray(Image.open(output).convert("RGB"))
    assert rgb.shape == (512, 512, 3) and rgb.max() > 100
    images[mode] = rgb
    record = {
        "returncode": result.returncode,
        "metal_api_validation": mac,
        "native_upscaler_executed": mac and mode != "disabled",
    }
    if mode != "disabled":
        delta = np.abs(rgb.astype(int) - images["disabled"].astype(int))
        record.update(
            mae_vs_bilinear=float(delta.mean()),
            changed_pixels=int(np.any(delta > 0, axis=2).sum()),
        )
        if mac:
            assert record["changed_pixels"] > 1000, record
    records[mode] = record
    print(mode, record, flush=True)
canvas = Image.new("RGB", (1536, 536), "white")
draw = ImageDraw.Draw(canvas)
for i, (mode, rgb) in enumerate(images.items()):
    canvas.paste(Image.fromarray(rgb), (512 * i, 24))
    draw.text(
        (512 * i + 8, 5),
        f"Bevy 0.20: {mode}" + ("" if mac else " (native API unavailable)"),
        fill="black",
    )
canvas.save(evidence / "comparison.png")
(evidence / "results.json").write_text(json.dumps(records, indent=2) + "\n")
