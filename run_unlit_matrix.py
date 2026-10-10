# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.4.6", "pillow==12.3.0"]
# ///
"""Compare original and patched Solari unlit output with deferred and forward raster.

Solari reads the deferred G-buffer, so deferred raster is the exact reference.
Forward raster is a second control; some colors differ from it by a few levels
because of the G-buffer's RGB9E5 packing. A Solari camera with forward
materials bypasses Solari entirely and is kept only as that bypass control.

`--verify-existing RUN` reruns every assertion on a recorded run folder without
capturing: RUN is only read and the new report goes to a fresh folder.
"""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from repro_run import (
    ROOT,
    VALIDATION_LINE,
    binary_fingerprint,
    fresh_root,
    require_validation,
    sanitize,
)
from unlit_checks import (
    check_images,
    check_pair,
    comparison,
    load,
    matches_recorded,
    stage_cases,
)

parser = argparse.ArgumentParser()
parser.add_argument("--before", help="binary with the dispatch change only")
parser.add_argument("--after", help="binary with the unlit change as well")
parser.add_argument(
    "--verify-existing",
    metavar="RUN",
    help="recheck a recorded run folder offline; nothing is captured or rewritten",
)
parser.add_argument(
    "--out", help="new folder (default: timestamped, outside the checkout)"
)
args = parser.parse_args()
if args.verify_existing is None and not (args.before and args.after):
    parser.error("--before and --after are required unless --verify-existing is given")
if args.verify_existing is not None and (args.before or args.after):
    parser.error("--verify-existing reads recorded images; do not pass binaries")


def tree_digest(folder):
    """SHA-256 over every file's relative path and content."""
    digest = hashlib.sha256()
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    for path in files:
        digest.update(str(path.relative_to(folder)).encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest(), len(files)


def verify_existing(run):
    if args.out is not None:
        requested = Path(args.out).resolve()
        assert requested != run and run not in requested.parents, "--out is inside RUN"
    out = fresh_root(args.out, "unlit-verify")
    digest_before = tree_digest(run)
    recorded = json.loads((run / "results.json").read_text())
    expected = [
        (stage, name, flags)
        for stage in ("before", "after")
        for name, _, flags in stage_cases()
    ]
    found = [(r["stage"], r["case"], r["flags"]) for r in recorded["records"]]
    assert found == expected, "recorded cases differ from this matrix"
    images = {}
    for record in recorded["records"]:
        stage, name = record["stage"], record["case"]
        log = (run / stage / f"{name}.txt").read_text()
        assert "160 updates completed" in log, (stage, name)
        # Metal runs must show the runtime's validation line; other hosts never do.
        assert record["metal_api_validation"] in (True, None), record
        assert (VALIDATION_LINE in log) == bool(record["metal_api_validation"]), record
        images[stage, name] = load(run / stage / f"{name}.png")
    checks = check_images(images)
    matches_recorded(recorded["checks"], checks)
    if "binaries" in recorded:
        check_pair(recorded["binaries"])
        provenance = "binary names, SHA-256 and WGSL markers recorded by the run"
    else:
        variants = run / "variants.json"
        built = sorted(json.loads(variants.read_text())) if variants.exists() else []
        provenance = (
            "unknown: this run did not record which binaries produced it, and no "
            "hash or pair is inferred; variants.json lists the variants built on "
            f"that host: {built}"
        )
    assert tree_digest(run) == digest_before, "recorded run changed during verification"
    name = str(run.relative_to(ROOT)) if ROOT in run.parents else run.name
    report = {
        "verified": name,
        "inputs_sha256": digest_before[0],
        "input_files": digest_before[1],
        "binaries": recorded.get("binaries"),
        "provenance": provenance,
        "metal_api_validation": sorted(
            {str(r["metal_api_validation"]) for r in recorded["records"]}
        ),
        "bypass": {
            key: value["whole_image_vs_forward_raster"]
            for key, value in checks.items()
            if "bypass" in key
        },
        "checks": checks,
    }
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {k: report[k] for k in ("verified", "provenance", "bypass")}, indent=1
        )
    )


if args.verify_existing is not None:
    verify_existing(Path(args.verify_existing).resolve())
    raise SystemExit
binaries = {
    "before": binary_fingerprint(args.before),
    "after": binary_fingerprint(args.after),
}
check_pair(binaries)
out = fresh_root(args.out, "unlit")


def capture(stage, binary, name, flags):
    folder = out / stage
    folder.mkdir(exist_ok=True)
    output = folder / f"{name}.png"
    result = subprocess.run(
        [binary, "--unlit", "--out", str(output), *flags],
        env={**os.environ, "MTL_DEBUG_LAYER": "1"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    log = sanitize(result.stdout + result.stderr, out)
    (folder / f"{name}.txt").write_text(log)
    assert result.returncode == 0 and output.is_file(), log
    assert "160 updates completed" in log, log
    return load(output), require_validation(log)


images = {}
records = []
for stage, binary in (("before", args.before), ("after", args.after)):
    for name, refs, flags in stage_cases():
        image, validation = capture(stage, binary, name, flags)
        images[stage, name] = image
        records.append(
            {
                "stage": stage,
                "case": name,
                "flags": flags,
                "metal_api_validation": validation,
            }
        )
        print(stage, name, flush=True)

# Shared build caches must not replace a binary during a capture sequence.
assert binaries == {
    "before": binary_fingerprint(args.before),
    "after": binary_fingerprint(args.after),
}, "A capture binary changed during the run"
checks = check_images(images)
comparison(images).save(out / "comparison.png")
(out / "results.json").write_text(
    json.dumps({"binaries": binaries, "records": records, "checks": checks}, indent=2)
    + "\n"
)
print(json.dumps({k: v for k, v in checks.items() if k.startswith("lit")}, indent=1))
