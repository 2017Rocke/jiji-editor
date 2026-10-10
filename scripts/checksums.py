from pathlib import Path
import hashlib
import platform
root = Path("output")
system = "Windows" if platform.system() == "Windows" else "macOS"
arch = "x64" if system == "Windows" else platform.machine()
packages = sorted(root.glob(f"JijiEditor-*-{system}-{arch}.zip"))
if not packages:
    raise SystemExit("No release archive found")
lines = [hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name for p in packages]
(root / f"SHA256SUMS-{system}-{arch}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
