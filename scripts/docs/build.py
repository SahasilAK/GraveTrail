"""Build strictly and inspect precisely the artifact that will be uploaded to Pages."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

if __name__ == "__main__":
    subprocess.run([sys.executable, "-m", "scripts.docs.inventory", "--check"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-m", "mkdocs", "build", "--strict", "--clean"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-m", "scripts.docs.validate"], cwd=ROOT, check=True)
