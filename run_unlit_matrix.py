# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.4.6", "pillow==12.3.0"]
# ///
"""Compare original and patched Solari unlit output with deferred and forward raster.

Solari reads the deferred G-buffer, so deferred raster is the exact reference.
Forward raster is a second control; some colors differ from it by a few levels
because of the G-buffer's RGB9E5 packing. A Solari camera with forward
materials bypasses Solari entirely and is kept only as that bypass control.
"""

import argparse
import json
import os
import subprocess
import numpy as np
from PIL import Image, ImageDraw
from repro_run import fresh_root, require_validation, sanitize

FIXTURE = (128, 32, 32)
BLUE = (32, 32, 128)
COLORS = [(255, 4, 4), (200, 10, 120), (250, 250, 1)]
EVS = (9.7, 3.0, 0.0)

parser = argparse.ArgumentParser()
parser.add_argument(
    "--before", required=True, help="binary with the dispatch change only"
)
parser.add_argument(
    "--after", required=True, help="binary with the unlit change as well"
)
parser.add_argument(
    "--out", help="new folder (default: timestamped, outside the checkout)"
)
args = parser.parse_args()
out = fresh_root(args.out, "unlit")


def group(prefix, colors, flags):
    """Forward/deferred raster references, then Solari cases compared against them."""
    forward, deferred = f"{prefix}raster-forward", f"{prefix}raster-deferred"
    refs = (forward, deferred, colors)
    yield forward, refs, ["--raster", *flags]
    yield deferred, refs, ["--raster", "--deferred", *flags]
    for restir in (0, 1):
        yield f"{prefix}solari-restir{restir}", refs, flags + ["--restir"] * restir


def cases():
    """(name, (forward reference, deferred reference, authored colors), flags)."""
    for ev in EVS:
        e = ["--ev", f"{ev:g}"]
        refs = None
        for name, refs, flags in group(f"ev{ev:g}-", [FIXTURE], e):
            yield name, refs, flags
        # Solari camera, forward materials: Solari is bypassed, so ReSTIR is moot.
        yield f"ev{ev:g}-bypass-forward-materials", refs, ["--forward", *e]
    yield from group("texture-", [FIXTURE, BLUE], ["--texture"])
    for color in COLORS:
        tag = "color" + "-".join(map(str, color)) + "-"
        yield from group(tag, [color], ["--color", ",".join(map(str, color))])
    for restir in (0, 1):
        # Ordinary lit material with the same color: the patch must leave it alone.
        yield f"lit-solari-restir{restir}", None, ["--lit-cube"] + ["--restir"] * restir


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
    return np.asarray(Image.open(output).convert("RGB")).astype(
        int
    ), require_validation(log)


def interior(image, colors):
    """Pixels exactly matching the authored colors, eroded to exclude all edges."""
    mask = np.zeros(image.shape[:2], bool)
    for color in colors:
        mask |= np.all(image == color, axis=2)
    for axis in (0, 1):
        mask &= np.roll(mask, 2, axis) & np.roll(mask, -2, axis)
    return mask


def error(image, reference, mask):
    delta = np.abs(image[mask] - reference[mask])
    return {"max": int(delta.max()), "mean": round(float(delta.mean()), 4)}


images = {}
records = []
for stage, binary in (("before", args.before), ("after", args.after)):
    # A second lit capture with the same binary is the run-to-run noise baseline.
    repeats = [
        (
            f"lit-solari-restir{restir}-repeat",
            None,
            ["--lit-cube"] + ["--restir"] * restir,
        )
        for restir in (0, 1)
    ]
    for name, refs, flags in [*cases(), *repeats]:
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

checks = {}
for name, refs, flags in cases():
    if refs is None:
        continue
    forward_name, deferred_name, colors = refs
    # Raster does not involve Solari; both stages must be bit-identical.
    if "raster" in name:
        assert np.array_equal(images["before", name], images["after", name]), name
    forward = images["before", forward_name]
    deferred = images["before", deferred_name]
    mask = interior(forward, colors)
    assert mask.sum() > 1000, f"{forward_name} failed to expose the authored color"
    for stage in ("before", "after"):
        image = images[stage, name]
        check = {
            "pixels": int(mask.sum()),
            "vs_deferred_raster": error(image, deferred, mask),
            "vs_forward_raster": error(image, forward, mask),
            "median_rgb": np.median(image[mask], axis=0).tolist(),
        }
        if "solari" in name:
            if stage == "after":
                assert check["vs_deferred_raster"]["max"] == 0, (name, check)
            else:
                assert check["vs_deferred_raster"]["mean"] > 1, (name, check)
        if name.startswith("bypass"):
            # Solari camera with forward materials renders exactly like plain raster.
            assert np.array_equal(image, forward), name
            check["identical_to_forward_raster"] = True
        if colors == [FIXTURE] and "raster" in name:
            # This fixture color survives RGB9E5 packing within one level.
            assert check["vs_forward_raster"]["max"] <= 1, (name, check)
        checks[f"{stage}/{name}"] = check
for restir in (0, 1):
    name = f"lit-solari-restir{restir}"
    stats = {}
    for label, a, b in (
        ("before_vs_after", images["before", name], images["after", name]),
        (
            "after_repeat_noise",
            images["after", name],
            images["after", f"{name}-repeat"],
        ),
        (
            "before_repeat_noise",
            images["before", name],
            images["before", f"{name}-repeat"],
        ),
    ):
        delta = np.abs(a - b).max(axis=2)
        stats[label] = {
            "max": int(delta.max()),
            "fraction_over_2": round(float((delta > 2).mean()), 6),
        }
    # Lit output is noisy run to run; the patch must not add a systematic change.
    assert stats["before_vs_after"]["fraction_over_2"] < 0.001, stats
    checks[name] = stats

rows = [
    ("EV 9.7", "ev9.7-raster-forward", "ev9.7-raster-deferred", "ev9.7-solari-restir1"),
    (
        "Texture",
        "texture-raster-forward",
        "texture-raster-deferred",
        "texture-solari-restir1",
    ),
    (
        "255,4,4",
        "color255-4-4-raster-forward",
        "color255-4-4-raster-deferred",
        "color255-4-4-solari-restir1",
    ),
]
tile = 256
canvas = Image.new("RGB", (tile * 4, len(rows) * (tile + 20)), "white")
draw = ImageDraw.Draw(canvas)
for row, (label, forward, deferred, solari) in enumerate(rows):
    for column, (title, key) in enumerate(
        (
            ("forward raster", ("before", forward)),
            ("deferred raster", ("before", deferred)),
            ("original Solari", ("before", solari)),
            ("patched Solari", ("after", solari)),
        )
    ):
        y = row * (tile + 20)
        picture = Image.fromarray(images[key].astype("uint8")).resize((tile, tile))
        canvas.paste(picture, (column * tile, y + 20))
        draw.text((column * tile + 4, y + 4), f"{label}: {title}", fill="black")
canvas.save(out / "comparison.png")
(out / "results.json").write_text(
    json.dumps({"records": records, "checks": checks}, indent=2) + "\n"
)
print(json.dumps({k: v for k, v in checks.items() if k.startswith("lit")}, indent=1))
