"""Verify the actual Windows desktop window and its embedded WebView2 renderer."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pymupdf as fitz
from PIL import Image

executable = Path(sys.argv[1]).resolve()
package = executable.parent
for required in ('coreclr.dll', 'hostfxr.dll', 'System.Private.CoreLib.dll',
                 'System.Windows.Forms.dll', 'JijiEditor.runtimeconfig.json',
                 'webview2/msedgewebview2.exe', 'webview2-runtime.json'):
    assert (package / required).is_file(), f'Portable package is missing {required}'
manifest = json.loads((package / 'webview2-runtime.json').read_text(encoding='utf-8-sig'))
output = Path('output/native-windows').resolve()
output.mkdir(parents=True, exist_ok=True)
for name in ('native-verification.json', 'native-export.pdf', 'native-recovery-export.pdf', 'native-window.png'):
    (output / name).unlink(missing_ok=True)
process = subprocess.Popen([str(executable), '--verify-native', str(output)])
try:
    result = process.wait(timeout=150)
except subprocess.TimeoutExpired:
    process.kill()
    process.wait()
    raise RuntimeError('Windows desktop verification timed out') from None
report_path = output / 'native-verification.json'
if not report_path.exists():
    raise RuntimeError(f'Windows desktop did not produce its verification report (exit {result})')
report = json.loads(report_path.read_text(encoding='utf-8-sig'))
checks = ('ready', 'embeddedWebView', 'batchCrop', 'undo', 'pdfExport',
          'saveCancelledKeepsDirty', 'closeGuard', 'recoverySaveCancelledKeepsDirty',
          'recoveryPdfExport', 'recoveryCloseGuard', 'selfContainedDotNet', 'bundledWebView2')
for check in checks:
    if report.get(check) is not True:
        raise AssertionError(f'Windows desktop check failed: {check}; {report.get("error", "no detail")}')
if result != 0:
    raise RuntimeError(f'Windows desktop verification exited with status {result}')
for field, expected in (('dotnetRuntimeDirectory', package),
                        ('dotnetRuntimeModule', package / 'coreclr.dll'),
                        ('webView2Executable', package / 'webview2/msedgewebview2.exe')):
    value = report.get(field)
    assert isinstance(value, str) and value, f'Missing runtime location proof: {field}'
    actual = (package / value).resolve()
    assert os.path.normcase(str(actual)) == os.path.normcase(str(expected.resolve())), \
        f'Runtime was not loaded from the portable package: {field}'
assert str(report.get('dotnetRuntimeVersion', '')).startswith('10.'), 'Expected the bundled .NET 10 runtime'
assert report.get('webView2RuntimeVersion') == manifest['version'], 'WebView2 version differs from the locked runtime'
assert report.get('bundledWebView2ExpectedVersion') == manifest['version'], 'Bundled runtime manifest mismatch'
if os.environ.get('JIJI_OFFLINE_PROBE_ADDRESS'):
    assert report.get('outboundProbeBlocked') is True, 'The application outbound firewall probe was not blocked'
with fitz.open(output / 'native-export.pdf') as document:
    assert len(document) == 3, 'Native export lost pages'
    assert all(page.rect.width > 0 and page.rect.height > 0 for page in document)
    exported_rotations = [page.rotation for page in document]
with fitz.open(output / 'native-recovery-export.pdf') as recovered:
    assert len(recovered) == 3, 'Recovery export lost pages'
    assert all(page.rect.width > 0 and page.rect.height > 0 for page in recovered)
    assert [page.rotation for page in recovered] == [
        (rotation + 90) % 360 if index in (0, 2) else rotation
        for index, rotation in enumerate(exported_rotations)
    ], 'Recovery export did not preserve the latest unsaved page edits'
with Image.open(output / 'native-window.png') as screenshot:
    assert screenshot.width >= 900 and screenshot.height >= 600, 'Native window screenshot is incomplete'
summary = {check: True for check in checks}
summary['dotnetRuntimeVersion'] = report['dotnetRuntimeVersion']
summary['webView2RuntimeVersion'] = report['webView2RuntimeVersion']
if 'outboundProbeBlocked' in report:
    summary['outboundProbeBlocked'] = report['outboundProbeBlocked']
summary['passed'] = True
Path('output/native-windows-verification.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary))
