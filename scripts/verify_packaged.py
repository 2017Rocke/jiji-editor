"""Exercise the shipped executable, including fonts/assets and loopback APIs."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

import pymupdf as fitz

parser = argparse.ArgumentParser()
parser.add_argument("executable")
parser.add_argument("--out", default="output/packaged-verification.json")
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix="jiji-package-test-") as temp:
    urlfile = Path(temp) / "server.url"
    process = subprocess.Popen([str(Path(args.executable).resolve()), "--no-browser", "--url-file", str(urlfile)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(150):
            if urlfile.exists() and urlfile.stat().st_size:
                break
            if process.poll() is not None:
                raise RuntimeError("Packaged application exited before starting.")
            time.sleep(.2)
        url = urllib.parse.urlsplit(urlfile.read_text())
        origin = f"{url.scheme}://{url.netloc}"
        token = urllib.parse.parse_qs(url.fragment)["token"][0]
        def api(route, payload=None):
            request = urllib.request.Request(origin + route, headers={"X-Jiji-Token": token, "Content-Type": "application/json"}, data=json.dumps(payload).encode() if payload is not None else None)
            with urllib.request.urlopen(request, timeout=30) as response:
                result = response.read()
                return json.loads(result) if "json" in response.headers.get("Content-Type", "") else result
        html = api("/").decode()
        assert "吉吉编辑软件" in html
        state = api("/api/sample", {})
        assert len(state["pages"]) == 3
        state = api("/api/edit", {"action": "text", "page": 0, "rect": [.08, .78, .9, .88], "text": "跨平台打包验证", "size": 18, "revision": state["revision"]})
        assert api("/api/render?page=0&scale=.5").startswith(b"\x89PNG")
        pdf = api("/api/export")
        with fitz.open(stream=pdf, filetype="pdf") as doc:
            assert len(doc) == 3
            assert "跨平台打包验证" in doc[0].get_text()
        report = {"passed": True, "pages": 3, "chineseText": True, "render": True, "export": True}
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
