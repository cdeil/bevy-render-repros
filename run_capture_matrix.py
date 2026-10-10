# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.4.6", "pillow==12.3.0"]
# ///
"""Separate incorrect registration order from asynchronous pipeline warmup."""

import argparse
import json
import os
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from repro_run import fresh_root, require_validation, sanitize

RED = (255, 0, 0)
parser = argparse.ArgumentParser()
parser.add_argument(
    "--out", help="new folder (default: timestamped, outside the checkout)"
)
args = parser.parse_args()
target = Path(os.environ["CARGO_TARGET_DIR"]) / "release" / "bevy-capture-repro"
out = fresh_root(args.out, "capture")
clear = None


def classify(image):
    """unwritten: target never written; clear: pass ran without the marker."""
    red = int(np.all(image == RED, axis=2).sum())
    if not image.any():
        state = "unwritten"
    elif clear is not None and np.all(image == clear, axis=2).all():
        state = "clear-only"
    elif red:
        state = "marker"
    else:
        state = "other"
    return red, state


records = []
for name, flags in (
    ("early-sync", []),
    ("early-async", ["--async"]),
    ("adjacent-sync", ["--adjacent-late"]),
    ("adjacent-async", ["--adjacent-late", "--async"]),
    ("late-sync", ["--late"]),
    ("late-async", ["--late", "--async"]),
):
    output = out / f"{name}.png"
    result = subprocess.run(
        [str(target), "--out", str(output), *flags],
        env={**os.environ, "MTL_DEBUG_LAYER": "1"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    log = sanitize(result.stdout + result.stderr, out)
    (out / f"{name}.txt").write_text(log)
    assert result.returncode == 0 and "Completed 160 updates" in log, log
    validation = require_validation(log)
    images = {
        frame: np.asarray(Image.open(out / f"{name}-{frame}.png").convert("RGB"))
        for frame in (0, 5, 100)
    }
    if clear is None:
        # The first mature correct frame defines the clear color: exactly two colors.
        colors = np.unique(images[100].reshape(-1, 3), axis=0)
        assert len(colors) == 2 and RED in map(tuple, colors), colors
        clear = next(c for c in map(tuple, colors) if c != RED)
        assert any(clear), "clear color must differ from an unwritten target"
    counts, states = {}, {}
    for frame, image in images.items():
        counts[str(frame)], states[str(frame)] = classify(image)
    if name.startswith("early"):
        assert counts["100"] > 2000 and states["100"] == "marker", (counts, states)
        mature = images[100]
        background = np.all(mature == clear, axis=2) | np.all(mature == RED, axis=2)
        assert background.all(), "mature frame must contain only marker and clear color"
    elif name.startswith("late"):
        # A failed load leaves a rendered, entirely clear frame; an unwritten target fails.
        assert states["100"] == "clear-only" and "Path not found" in log, (states, log)
    record = {
        "case": name,
        "red_pixels": counts,
        "request_state": states,
        "returncode": result.returncode,
        "metal_api_validation": validation,
    }
    records.append(record)
    print(record, flush=True)
(out / "results.json").write_text(
    json.dumps({"clear_color": list(map(int, clear)), "records": records}, indent=2)
    + "\n"
)
