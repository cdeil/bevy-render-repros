# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy==2.4.6"]
# ///
"""Original analytic sphere/rod/plane fixture with seeded radiance noise.

A functional MetalFX guide/history-reset diagnostic, not a physical path-tracer or
an image-quality benchmark. Static camera and objects mean motion is zero.
"""

import argparse
import json
from pathlib import Path

import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
width, height, frames = 320, 192, 32
focal = 1 / np.tan(np.deg2rad(55) / 2)
y, x = np.mgrid[:height, :width]
rays = np.stack(
    (
        (2 * (x + 0.5) / width - 1) * (width / height) / focal,
        (1 - 2 * (y + 0.5) / height) / focal,
        -np.ones_like(x),
    ),
    axis=-1,
)
rays /= np.linalg.norm(rays, axis=-1, keepdims=True)
identity = np.eye(4, dtype=np.float32)
clip = np.array(
    [
        [focal / (width / height), 0, 0, 0],
        [0, focal, 0, 0],
        [0, 0, 0, 0.1],
        [0, 0, -1, 0],
    ],
    dtype=np.float32,
)
sun = np.array([0.3, 0.8, 0.5])
sun /= np.linalg.norm(sun)


def analytic_scene(cut):
    distance = np.full((height, width), np.inf)
    normal = np.zeros((height, width, 3))
    albedo = np.zeros_like(normal)
    specular = np.zeros_like(normal)
    roughness = np.ones((height, width))

    def hit(t, n, color, gloss=False):
        select = (t > 0) & (t < distance)
        distance[select] = t[select]
        normal[select] = np.broadcast_to(n, normal.shape)[select]
        albedo[select] = color
        specular[select] = 0.6 if gloss else 0.04
        roughness[select] = 0.3 if gloss else 0.8

    # Plane y=-1; camera at origin looking along -Z.
    plane = np.full_like(distance, np.inf)
    np.divide(-1.0, rays[..., 1], out=plane, where=rays[..., 1] < -1e-5)
    hit(plane, np.array([0, 1, 0]), [0.35, 0.35, 0.35])

    def sphere(center, radius, color, gloss=False):
        center = np.asarray(center)
        b = np.sum(rays * -center, axis=-1)
        discriminant = b * b - (np.dot(center, center) - radius * radius)
        t = -b - np.sqrt(np.maximum(discriminant, 0))
        t[discriminant < 0] = np.inf
        points = rays * np.where(np.isfinite(t), t, 0)[..., None]
        hit(t, (points - center) / radius, color, gloss)

    sphere([-0.8 if not cut else 0.8, -0.3, -3.5], 0.65, [0.7, 0.12, 0.06], True)
    # Procedural metal bars: sphere chain approximates round rods and tests fine edges.
    for bar_x in (-0.45, 0, 0.45):
        for bar_y in np.linspace(-0.8, 0.7, 15):
            sphere([bar_x, bar_y, -5.0], 0.055, [0.4, 0.5, 0.6], True)

    finite = np.isfinite(distance)
    points = rays * np.where(finite, distance, 0)[..., None]
    shade = 0.15 + 0.85 * np.maximum(np.sum(normal * sun, axis=-1), 0)
    clean = albedo * shade[..., None]
    clean[~finite] = [0.015, 0.025, 0.04]
    return finite, points, normal, albedo, specular, roughness, clean


for frame in range(frames):
    finite, points, normal, albedo, specular, roughness, clean = analytic_scene(
        frame >= 16
    )
    rng = np.random.default_rng(20261010 + frame)
    # Shared multiplicative noise has known expectation 1, avoiding chromatic artifacts.
    noisy = clean * rng.exponential(1.0, (height, width, 1))
    packed = np.zeros((height, width, 24), dtype="<f4")
    packed[..., :3] = noisy
    packed[..., 3] = 1
    np.divide(0.1, -points[..., 2], out=packed[..., 4], where=finite)
    packed[..., 12:15] = albedo
    packed[..., 15] = 1
    packed[..., 16:19] = specular
    packed[..., 19] = 1
    packed[..., 20:23] = normal
    packed[..., 23] = roughness
    stem = args.output / f"{frame:04d}"
    stem.with_suffix(".bin").write_bytes(packed.tobytes())
    meta = {
        "width": width,
        "height": height,
        "jitter": [0, 0],
        "world_to_view": identity.flatten(order="F").tolist(),
        "view_to_clip": clip.flatten(order="F").tolist(),
        "reset_history": frame == 16,
    }
    stem.with_suffix(".json").write_text(json.dumps(meta) + "\n")
    (args.output / f"{frame:04d}-reference.bin").write_bytes(
        clean.astype("<f4").tobytes()
    )
print(
    f"Generated {frames} analytic frames, object teleport/reset at frame 16; {width}x{height}"
)
