# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.4.6", "pillow==12.3.0"]
# ///
"""Separate incorrect registration order from asynchronous pipeline warmup."""

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

root = Path(__file__).resolve().parent
target = Path(os.environ["CARGO_TARGET_DIR"]) / "release" / "bevy-capture-repro"
host = "mac" if sys.platform == "darwin" else "linux"
evidence = root / "evidence" / f"capture-{host}"
evidence.mkdir(parents=True, exist_ok=True)
records = []
for name, flags in (
    ("early-sync", []),
    ("early-async", ["--async"]),
    ("adjacent-sync", ["--adjacent-late"]),
    ("adjacent-async", ["--adjacent-late", "--async"]),
    ("late-sync", ["--late"]),
    ("late-async", ["--late", "--async"]),
):
    output = evidence / f"{name}.png"
    for frame in (0, 5, 100):
        output.with_name(f"{name}-{frame}.png").unlink(missing_ok=True)
    result = subprocess.run(
        [str(target), "--out", str(output), *flags],
        env={**os.environ, "MTL_DEBUG_LAYER": "1"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    log = (result.stdout + result.stderr).replace(str(root), "$REPRO_REPO")
    (evidence / f"{name}.txt").write_text(log)
    assert result.returncode == 0 and "Completed 160 updates" in log, log
    counts = {}
    for frame in (0, 5, 100):
        image = np.asarray(
            Image.open(output.with_name(f"{name}-{frame}.png")).convert("RGB")
        )
        counts[str(frame)] = int(np.all(image == [255, 0, 0], axis=2).sum())
    if "early" in name:
        assert counts["100"] > 2000, counts
    elif "late" in name:
        assert counts["100"] == 0 and "Path not found" in log, log
    record = {
        "case": name,
        "red_pixels": counts,
        "returncode": result.returncode,
        "metal_api_validation": host == "mac",
    }
    records.append(record)
    print(record, flush=True)
(evidence / "results.json").write_text(json.dumps(records, indent=2) + "\n")
