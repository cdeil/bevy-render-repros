# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.4.6", "pillow==12.3.0", "pytest==9.1.1"]
# ///
"""Offline tests: recorded unlit evidence passes, and injected corruption fails.

No GPU is used. Recorded runs are copied into pytest's temporary folder before
they are corrupted, so `evidence/` is only read.

    uv run --script test_offline_checks.py
"""

import json
import os
import shutil
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

import repro_run
from repro_run import ROOT, binary_fingerprint, fresh_root
from unlit_checks import (
    BYPASS_MAX_FRACTION,
    DISPATCH,
    UNLIT,
    check_bypass,
    check_pair,
    interior,
    load,
)

RUNNER = ROOT / "run_unlit_matrix.py"
BYPASS = "ev9.7-bypass-forward-materials"
HOSTS = ("mac", "linux")


def verify(run, out):
    return subprocess.run(
        ["uv", "run", "--script", str(RUNNER), "--verify-existing", str(run)]
        + ["--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )


def git_status(path):
    return subprocess.run(
        ["git", "status", "--porcelain", "--", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture(params=HOSTS)
def recorded(request, tmp_path):
    """A private copy of one host's recorded unlit run."""
    source = ROOT / "evidence" / f"unlit-controls-{request.param}"
    copy = tmp_path / "run"
    shutil.copytree(source, copy)
    return request.param, copy


def floor_pixels(run, count):
    """Pixels outside the cube mask, so only the whole-image bound can see them."""
    forward = load(run / "before/ev9.7-raster-forward.png")
    outside = ~interior(forward, [(128, 32, 32)])
    ys, xs = np.nonzero(outside[:256, :256])
    return ys[:count], xs[:count]


def shift(run, stages, pixels, levels):
    """Add `levels` to the green channel of the bypass image at the given pixels."""
    for stage in stages:
        path = run / stage / f"{BYPASS}.png"
        image = load(path)
        ys, xs = pixels
        green = image[ys, xs, 1]
        image[ys, xs, 1] = np.where(
            green + levels <= 255, green + levels, green - levels
        )
        Image.fromarray(image.astype("uint8")).save(path)


# Whole-image bypass bound on synthetic images.


def test_bypass_bound_accepts_one_level_on_small_fraction():
    reference = np.full((100, 100, 3), 200)
    image = reference.copy()
    image[:10, 0, 0] -= 1  # 10 of 10,000 pixels = 0.001
    delta = check_bypass(image, reference)
    assert delta["differing_pixels"] == 10 and delta["levels"] == {"0": 9990, "1": 10}


def test_bypass_bound_rejects_two_levels():
    reference = np.full((100, 100, 3), 200)
    image = reference.copy()
    image[0, 0, 2] += 2
    with pytest.raises(AssertionError):
        check_bypass(image, reference)


def test_bypass_bound_rejects_large_fraction():
    reference = np.full((100, 100, 3), 200)
    image = reference.copy()
    image[:11, 0, 0] -= 1  # 0.0011 > BYPASS_MAX_FRACTION
    assert 11 / 10_000 > BYPASS_MAX_FRACTION
    with pytest.raises(AssertionError):
        check_bypass(image, reference)


# Recorded evidence, unchanged and corrupted.


def test_recorded_evidence_passes_on_both_hosts(recorded, tmp_path):
    host, run = recorded
    result = verify(run, tmp_path / "report")
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report/results.json").read_text())
    # All six bypass checks ran: three EVs, two stages.
    assert len(report["bypass"]) == 6
    worst = report["bypass"][f"before/{BYPASS}"]
    assert report["bypass"][f"after/{BYPASS}"] == worst
    if host == "linux":
        assert (worst["max"], worst["differing_pixels"]) == (1, 160)
        assert worst["bbox_xyxy"] == [487, 499, 511, 511]
    others = [v for k, v in report["bypass"].items() if BYPASS not in k]
    others += [worst] if host == "mac" else []
    assert all(v["differing_pixels"] == 0 for v in others)
    assert report["binaries"] is None and report["provenance"].startswith("unknown")


def test_committed_evidence_is_only_read(tmp_path):
    for host in HOSTS:
        run = ROOT / "evidence" / f"unlit-controls-{host}"
        before = git_status(run)
        result = verify(run, tmp_path / f"report-{host}")
        assert result.returncode == 0, result.stderr
        assert git_status(run) == before == ""


def test_bypass_two_levels_fails(recorded, tmp_path):
    _, run = recorded
    shift(run, ("before", "after"), floor_pixels(run, 1), 2)
    result = verify(run, tmp_path / "report")
    assert result.returncode != 0 and "differing_pixels" in result.stderr


def test_bypass_fraction_over_bound_fails(recorded, tmp_path):
    _, run = recorded
    # 300 more one-level pixels: over 0.1 % on both hosts, including Linux's 160.
    shift(run, ("before", "after"), floor_pixels(run, 300), 1)
    result = verify(run, tmp_path / "report")
    assert result.returncode != 0 and "differing_pixels" in result.stderr


def test_bypass_stage_difference_fails(recorded, tmp_path):
    _, run = recorded
    shift(run, ("after",), floor_pixels(run, 1), 1)
    result = verify(run, tmp_path / "report")
    assert result.returncode != 0 and BYPASS in result.stderr


def test_tampered_recorded_number_fails(recorded, tmp_path):
    _, run = recorded
    results = json.loads((run / "results.json").read_text())
    results["checks"][f"after/{BYPASS}"]["vs_forward_raster"]["max"] += 1
    (run / "results.json").write_text(json.dumps(results))
    assert verify(run, tmp_path / "report").returncode != 0


def test_missing_completion_or_validation_line_fails(recorded, tmp_path):
    host, run = recorded
    log = run / "after/ev3-solari-restir1.txt"
    text = log.read_text()
    if host == "mac":
        assert repro_run.VALIDATION_LINE in text
        log.write_text(text.replace(repro_run.VALIDATION_LINE, ""))
    else:
        log.write_text(text.replace("160 updates completed", ""))
    assert verify(run, tmp_path / "report").returncode != 0


def test_report_inside_recorded_run_is_refused(recorded):
    _, run = recorded
    result = verify(run, run / "report")
    assert result.returncode != 0 and not (run / "report").exists()


# Binary provenance.


def fingerprints(before, after):
    def markers(dispatch, unlit):
        return {"markers": {DISPATCH: dispatch, UNLIT: unlit}}

    return {"before": markers(*before), "after": markers(*after)}


def test_binary_fingerprint_reads_markers(tmp_path):
    binary = tmp_path / "bevy-scene-solari-struct-unlit"
    binary.write_bytes(b"\0" + DISPATCH.encode() + b"\0" + UNLIT.encode())
    fingerprint = binary_fingerprint(binary)
    assert fingerprint["name"] == binary.name and len(fingerprint["sha256"]) == 64
    assert fingerprint["markers"] == {DISPATCH: True, UNLIT: True}


def test_pair_requires_only_the_unlit_difference():
    check_pair(fingerprints((True, False), (True, True)))  # struct, struct-unlit
    check_pair(fingerprints((False, False), (False, True)))  # padding pair
    for before, after in (
        ((True, False), (False, True)),  # struct vs padding-unlit
        ((True, True), (True, True)),  # unlit in both
        ((True, False), (True, False)),  # unlit in neither
        ((True, True), (True, False)),  # reversed
    ):
        with pytest.raises(AssertionError):
            check_pair(fingerprints(before, after))


# fresh_root refusals, against a stand-in checkout so a failure cannot write here.


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    fake = (tmp_path / "checkout").resolve()
    (fake / "evidence").mkdir(parents=True)
    monkeypatch.setattr(repro_run, "ROOT", fake)
    link = tmp_path / "link"
    link.symlink_to(fake)
    return fake, link


def test_fresh_root_refuses_symlink_into_checkout(checkout):
    fake, link = checkout
    with pytest.raises(SystemExit):
        fresh_root(str(link / "evidence/new"), "test")
    assert not (fake / "evidence/new").exists()


def test_fresh_root_refuses_relative_path_from_symlinked_cwd(checkout, monkeypatch):
    fake, link = checkout
    monkeypatch.chdir(link)
    monkeypatch.setenv("PWD", str(link))
    with pytest.raises(SystemExit):
        fresh_root("evidence/new", "test")
    assert not (fake / "evidence/new").exists()


def test_fresh_root_refuses_existing_and_creates_new(checkout, tmp_path):
    with pytest.raises(SystemExit):
        fresh_root(str(tmp_path), "test")
    created = fresh_root(str(tmp_path / "fresh"), "test")
    assert created.is_dir() and created == (tmp_path / "fresh").resolve()


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(pytest.main([__file__, "-p", "no:cacheprovider", *sys.argv[1:]]))
