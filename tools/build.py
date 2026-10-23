"""Build a standalone, console-free Windows executable."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import make_icon


def main():
    artifacts = ROOT / "build"
    artifacts.mkdir(exist_ok=True)
    icon = artifacts / "CodexUsage.ico"
    make_icon().save(icon, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
        "--windowed", "--name", "CodexUsage", "--icon", str(icon),
        "--exclude-module", "numpy", "--exclude-module", "matplotlib",
        "--exclude-module", "pandas", "--exclude-module", "scipy",
        str(ROOT / "app.py"),
    ], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
