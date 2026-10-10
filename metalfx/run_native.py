# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.4.6", "pillow==12.3.0"]
# ///
"""Generate guides, run the three native replays with Metal validation and analyze.

Everything goes to one new run folder; `evidence/` inside it is the analysis output.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))
from repro_run import fresh_root, sanitize

parser = argparse.ArgumentParser()
parser.add_argument(
    "--out", help="new folder (default: timestamped, outside the checkout)"
)
args = parser.parse_args()
out = fresh_root(args.out, "metalfx-native")
(out / "logs").mkdir()


def run(name, command, env=None):
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, timeout=600, check=False
    )
    log = out / "logs" / f"{name}.log"
    log.write_text(sanitize(result.stdout + result.stderr, out))
    assert result.returncode == 0, log.read_text()[-3000:]
    print(f"{name}: ok", flush=True)
    return log


run("generate", [sys.executable, str(here / "generate_guides.py"), str(out / "guides")])
validation = {**os.environ, "MTL_DEBUG_LAYER": "1"}
replay = ["xcrun", "swift", str(here / "replay.swift"), str(out / "guides")]
logs = {}
for name, flags in (
    ("coherent", []),
    ("reset", ["--reset-every-frame"]),
    ("no-teleport-reset", ["--no-cut-reset"]),
):
    logs[name] = run(name, [*replay, str(out / name), *flags], validation)
run(
    "analyze",
    [
        sys.executable,
        str(here / "analyze.py"),
        str(out / "guides"),
        str(out / "coherent"),
        str(out / "reset"),
        str(out / "evidence"),
        "--coherent-log",
        str(logs["coherent"]),
        "--reset-log",
        str(logs["reset"]),
        "--no-teleport-reset",
        str(out / "no-teleport-reset"),
        "--no-teleport-reset-log",
        str(logs["no-teleport-reset"]),
    ],
)
print((out / "logs/analyze.log").read_text())
