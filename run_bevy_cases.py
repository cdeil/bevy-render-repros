import json
import os
import resource
import signal
import subprocess
import sys
from pathlib import Path

resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
root = Path(__file__).resolve().parent
target = Path(os.environ["CARGO_TARGET_DIR"]) / "release"
evidence = root / "evidence" / ("solari" if sys.platform == "darwin" else "solari-linux")
evidence.mkdir(parents=True, exist_ok=True)
records = []
for case, binary, flags in (
    ("raster", "bevy-scene-repro", ["--raster"]),
    ("solari", "bevy-scene-repro", []),
    ("solari-padded", "bevy-scene-patched-repro", []),
):
    output = evidence / f"{case}.png"
    output.unlink(missing_ok=True)
    result = subprocess.run(
        [str(target / binary), "--out", str(output), *flags],
        env={**os.environ, "MTL_DEBUG_LAYER": "1"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    log = (result.stdout + result.stderr).replace(str(root), "$REPRO_REPO")
    (evidence / f"{case}.txt").write_text(log)
    expected_layout_failure = sys.platform == "darwin" and case == "solari"
    if expected_layout_failure:
        assert result.returncode == -signal.SIGABRT, log
        assert "world_cache_active_cells_dispatch" in log and "length(16)" in log, log
        assert not output.exists()
    else:
        assert result.returncode == 0 and output.is_file(), log
        assert "160 updates completed" in result.stdout, log
    record = {
        "case": case,
        "returncode": result.returncode,
        "shell_exit": 128 - result.returncode if result.returncode < 0 else result.returncode,
        "screenshot": output.is_file(),
        "metal_api_validation": sys.platform == "darwin",
        "expected_layout_failure": expected_layout_failure,
    }
    records.append(record)
    print(record)
(evidence / "results.json").write_text(json.dumps(records, indent=2) + "\n")
