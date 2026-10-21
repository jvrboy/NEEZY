"""Assemble the Buildozer source tree in build/android-stage.

Copies the mobile front end and the shared backend, stubs the backend's
package __init__ (the mobile build only needs the modules it imports), and
vendors the pure-Python packages that have no python-for-android recipe.
Run from anywhere: python packaging/android/stage.py
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build" / "android-stage"
VENDORED = ["websocket-client==1.9.2", "certifi"]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def app_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit("version not found in pyproject.toml")
    return match.group(1)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    shutil.copytree(ROOT / "neezy_mobile", OUT / "neezy_mobile", ignore=IGNORE)
    shutil.copytree(ROOT / "neezy_backend", OUT / "neezy_backend", ignore=IGNORE)
    (OUT / "neezy_backend" / "__init__.py").write_text(
        '"""Mobile build: package marker only."""\n', encoding="utf-8"
    )
    shutil.copy(ROOT / "packaging" / "android" / "main.py", OUT / "main.py")

    spec = (ROOT / "packaging" / "android" / "buildozer.spec").read_text(
        encoding="utf-8"
    )
    spec = re.sub(r"(?m)^version = .*$", f"version = {app_version()}", spec)
    (OUT / "buildozer.spec").write_text(spec, encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-compile",
            "--target",
            str(OUT),
            *VENDORED,
        ],
        check=True,
    )
    shutil.rmtree(OUT / "bin", ignore_errors=True)
    print(f"staged {OUT}")


if __name__ == "__main__":
    main()
