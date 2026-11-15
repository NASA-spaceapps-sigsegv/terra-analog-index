import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_step_01_help_responds():
    out = subprocess.run(
        [sys.executable, "pipeline/01_grid.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--force" in out.stdout and "--bbox" in out.stdout
