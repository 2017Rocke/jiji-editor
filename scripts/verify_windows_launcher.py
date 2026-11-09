"""Verify the shipped Windows launcher, including manual browser recovery."""
import json
from pathlib import Path
import subprocess
import sys
target = Path("output/windows-launcher-verification.json").resolve()
target.parent.mkdir(parents=True, exist_ok=True)
target.unlink(missing_ok=True)
subprocess.run([str(Path(sys.argv[1]).resolve()), "--verify-launcher", str(target)], check=True, timeout=30)
report = json.loads(target.read_text(encoding="utf-8"))
checks = ("ready", "tk", "copyAddress", "browserFailureHint", "manualAddress")
for check in checks:
    assert report.get(check) is True, f"Windows launcher check failed: {check}"
print(json.dumps({check: report[check] for check in checks}))
