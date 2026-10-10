"""Shared helpers for the matrix scripts: fresh output roots, logs and validation.

Every run writes to a new folder outside this checkout and refuses to reuse an
existing one. Recorded evidence is therefore never rewritten by a script; a
reviewed run is added to `evidence/` under a new name by an explicit copy.
"""

import datetime
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAC = sys.platform == "darwin"
HOST = "mac" if MAC else "linux"
VALIDATION_LINE = "Metal API Validation Enabled"


def fresh_root(requested: str | None, name: str) -> Path:
    """Create a new run folder, defaulting to a timestamped folder outside the repo."""
    if requested is None:
        data = Path(
            os.environ.get("REPRO_DATA", Path.home() / "data/bevy-render-repros")
        )
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        requested = data / "runs" / f"{name}-{HOST}-{stamp}"
    path = Path(requested).absolute()
    if path == ROOT or ROOT in path.parents:
        sys.exit(
            f"Refusing to write inside the checkout: {path}. Copy reviewed runs instead."
        )
    if path.exists():
        sys.exit(f"Refusing to reuse existing output folder: {path}")
    path.mkdir(parents=True)
    print(f"Run folder: {path}", flush=True)
    return path


def sanitize(text: str, run_root: Path) -> str:
    """Replace machine-specific paths in captured logs with stable placeholders."""
    replacements = [(str(run_root), "$RUN_ROOT"), (str(ROOT), "$REPRO_REPO")]
    if "CARGO_TARGET_DIR" in os.environ:
        replacements.append((os.environ["CARGO_TARGET_DIR"], "$CARGO_TARGET_DIR"))
    replacements.append((str(Path.home()), "~"))
    for old, new in sorted(replacements, key=lambda pair: -len(pair[0])):
        text = text.replace(old, new)
    return text


def metal_validation(log: str) -> bool | None:
    """Metal API validation as reported by the Metal runtime; None off macOS."""
    return VALIDATION_LINE in log if MAC else None


def require_validation(log: str) -> bool | None:
    """On macOS, require the runtime's validation line rather than trusting the variable."""
    enabled = metal_validation(log)
    assert enabled is not False, (
        f"Missing '{VALIDATION_LINE}' in a Metal run:\n{log[-2000:]}"
    )
    return enabled
