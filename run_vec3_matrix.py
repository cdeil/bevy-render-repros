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
evidence = root / "evidence" / ("vec3" if sys.platform == "darwin" else "vec3-linux")
evidence.mkdir(parents=True, exist_ok=True)
records = []
for binary in ("wgpu-vec3-repro", "wgpu-main-vec3-repro"):
    for case, flags, validation in (
        ("uint12", [], "1"),
        ("uint16", ["--padded"], "1"),
        ("int12", ["--signed"], "1"),
        ("int16", ["--signed", "--padded"], "1"),
        ("float12", ["--float"], "1"),
        ("float16", ["--float", "--padded"], "1"),
        ("scalars12", ["--scalars"], "1"),
        ("uint12-unvalidated", [], "0"),
    ):
        command = [str(target / binary), *flags]
        result = subprocess.run(
            command,
            env={**os.environ, "MTL_DEBUG_LAYER": validation},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        name = f"{binary}-{case}.txt"
        (evidence / name).write_text(result.stdout + result.stderr)
        expected_layout_failure = (
            sys.platform == "darwin"
            and validation == "1"
            and "--padded" not in flags
            and "--scalars" not in flags
        )
        layout_assertion = "has space for 12 bytes, but argument has a length(16)" in result.stderr
        if expected_layout_failure:
            assert result.returncode == -signal.SIGABRT and layout_assertion, name
        else:
            assert result.returncode == 0 and "GPU readback verified" in result.stdout, name
        record = {
            "binary": binary,
            "case": case,
            "validation": validation == "1",
            "metal_api_validation": sys.platform == "darwin" and validation == "1",
            "expected_layout_failure": expected_layout_failure,
            "layout_assertion": layout_assertion,
            "process_returncode": result.returncode,
            "shell_exit": 128 - result.returncode
            if result.returncode < 0
            else result.returncode,
            "log": name,
            "readback_verified": "GPU readback verified" in result.stdout,
        }
        records.append(record)
        print(record)
    for case, flags in (("uint", []), ("scalars", ["--scalars"])):
        subprocess.run(
            [
                str(target / binary),
                *flags,
                "--msl",
                str(evidence / f"{binary}-{case}.metal"),
                "--translate-only",
            ],
            check=True,
        )
(evidence / "results.json").write_text(json.dumps(records, indent=2) + "\n")
