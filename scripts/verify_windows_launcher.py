"""Verify Tk initialization and the service thread inside the frozen Windows EXE."""
import json
from pathlib import Path
import subprocess
import sys
target = Path("output/windows-launcher-verification.json").resolve()
subprocess.run([str(Path(sys.argv[1]).resolve()), "--verify-launcher", str(target)], check=True, timeout=30)
report = json.loads(target.read_text())
assert report["ready"] and report["tk"]
print(json.dumps(report))
