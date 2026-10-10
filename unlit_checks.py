"""Packet 2 unlit matrix: case list and assertions shared by capture and offline checks.

`run_unlit_matrix.py` captures the images and `--verify-existing` reruns these same
assertions on a recorded run folder, so recorded evidence is checked by the code
that would have produced it.
"""

import numpy as np
from PIL import Image, ImageDraw

from repro_run import SOLARI_MARKERS

FIXTURE = (128, 32, 32)
BLUE = (32, 32, 128)
COLORS = [(255, 4, 4), (200, 10, 120), (250, 250, 1)]
EVS = (9.7, 3.0, 0.0)
# The bypass control renders through Solari's camera setup without Solari shading.
# It may differ from plain raster by one quantization level on a small part of the
# image (seen on Vulkan at EV 9.7), never by more. The bound is the same on every host.
BYPASS_MAX_LEVEL = 1
BYPASS_MAX_FRACTION = 0.001
DISPATCH = SOLARI_MARKERS["solari-dispatch-indirect-args.patch"]
UNLIT = SOLARI_MARKERS["solari-unlit-color.patch"]


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


def stage_cases():
    """Every capture of one stage: the cases plus a repeated lit noise baseline."""
    yield from cases()
    for restir in (0, 1):
        flags = ["--lit-cube"] + ["--restir"] * restir
        yield f"lit-solari-restir{restir}-repeat", None, flags


def load(path):
    return np.asarray(Image.open(path).convert("RGB")).astype(int)


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


def whole_image_delta(image, reference):
    """Per-pixel maximum channel difference over the whole image."""
    delta = np.abs(image - reference).max(axis=2)
    ys, xs = np.nonzero(delta)
    return {
        "max": int(delta.max()),
        "differing_pixels": len(ys),
        "differing_fraction": round(float(len(ys) / delta.size), 6),
        "bbox_xyxy": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        if len(ys)
        else None,
        "levels": {
            str(level): int((delta == level).sum()) for level in np.unique(delta)
        },
    }


def check_bypass(image, forward):
    """Whole bypass image against forward raster, within the quantization bound."""
    delta = whole_image_delta(image, forward)
    assert delta["max"] <= BYPASS_MAX_LEVEL, delta
    assert (
        delta["differing_pixels"]
        <= BYPASS_MAX_FRACTION * image.shape[0] * image.shape[1]
    ), delta
    return delta


def check_images(images):
    """Assert the whole matrix on {(stage, case): image}; return the checks."""
    checks = {}
    for name, refs, flags in cases():
        if refs is None:
            continue
        forward_name, deferred_name, colors = refs
        # Raster and the bypass control do not run Solari shading, so the patch
        # cannot change them: both stages must be bit-identical.
        if "raster" in name or "bypass" in name:
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
            if "bypass" in name:
                check["whole_image_vs_forward_raster"] = check_bypass(image, forward)
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
    return checks


def check_pair(binaries):
    """Before lacks the unlit WGSL, after has it, and both share the dispatch WGSL.

    The padding fallback changes only Rust, so markers cannot show whether either
    binary carries it; the dispatch marker shows only the struct change.
    """
    before, after = binaries["before"]["markers"], binaries["after"]["markers"]
    assert not before[UNLIT] and after[UNLIT], binaries
    assert before[DISPATCH] == after[DISPATCH], binaries


def matches_recorded(recorded, recomputed):
    """Every recorded check is reproduced exactly; only bypass deltas may be new."""
    assert recorded.keys() == recomputed.keys(), recorded.keys() ^ recomputed.keys()
    for key, values in recorded.items():
        fresh = recomputed[key]
        assert {k: fresh[k] for k in values} == values, (key, values, fresh)
        assert set(fresh) - set(values) <= {"whole_image_vs_forward_raster"}, key


def comparison(images):
    rows = [
        (
            "EV 9.7",
            "ev9.7-raster-forward",
            "ev9.7-raster-deferred",
            "ev9.7-solari-restir1",
        ),
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
    return canvas
