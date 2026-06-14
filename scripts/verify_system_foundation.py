from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = os.environ.get("KENRADAR_PYTHON", "/home/ken/miniconda3/envs/openclaw/bin/python")


def run_step(title: str, cmd: list[str], cwd: Path) -> None:
    print(f"\n==> {title}")
    print("   ", " ".join(shlex.quote(part) for part in cmd))
    subprocess.run(cmd, cwd=str(cwd), check=True)


def main() -> int:
    run_step("Compile Python modules", [PYTHON, "-m", "compileall", "-q", "kenradar", "tests"], ROOT)
    run_step("Focused pytest", [PYTHON, "-m", "pytest", "tests/test_config_and_publishing.py", "-q"], ROOT)
    run_step("Database and secret doctor", [PYTHON, "-m", "kenradar", "--config", "config/config.yaml", "doctor"], ROOT)
    run_step("Frontend lint", ["npm", "run", "lint"], ROOT / "kenradar" / "web" / "frontend")
    print("\nAll foundation checks passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"\nVerification failed with exit code {exc.returncode}.", file=sys.stderr)
        raise SystemExit(exc.returncode)
