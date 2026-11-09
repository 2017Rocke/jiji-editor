"""Exercise the packaged desktop, including real denied Windows directory ACLs."""
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

import pymupdf as fitz
from PIL import Image


CHECKS = ('ready', 'embeddedWebView', 'batchCrop', 'undo', 'pdfExport',
          'saveCancelledKeepsDirty', 'closeGuard', 'recoverySaveCancelledKeepsDirty',
          'recoveryPdfExport', 'recoveryCloseGuard', 'selfContainedDotNet',
          'bundledWebView2', 'startupDiagnostics')
STORAGE_CHECKS = ('privateDataRoot', 'profileUnderDataRoot', 'sessionUnderDataRoot',
                  'backendTempUnderDataRoot', 'processTempUnderDataRoot',
                  'tempRootWritable', 'diagnosticsRootWritable', 'diagnosticsUnderDataRoot')
OUTPUT_FILES = ('native-verification.json', 'native-export.pdf', 'native-recovery-export.pdf',
                'native-window.png', 'native-startup-diagnostic.json')


def verify_diagnostic_privacy(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            assert key.lower() not in {'message', 'stacktrace', 'url', 'token', 'filename', 'path'}, \
                f'Diagnostic unexpectedly includes a sensitive field: {key}'
            verify_diagnostic_privacy(nested)
    elif isinstance(value, list):
        for nested in value:
            verify_diagnostic_privacy(nested)
    elif isinstance(value, str):
        assert not re.match(r'^(?:[A-Za-z]:[\\/]|/|\\\\)', value), \
            'Diagnostic leaked an absolute filesystem path'
        assert not any(marker in value for marker in ('DIAGNOSTIC_TOKEN_SENTINEL', 'private-invoice.pdf',
                                                       'SensitiveProfile', '127.0.0.1', 'token=')), \
            'Diagnostic leaked an injected private exception message'


def verify_run(executable, output, environment):
    """Repeat all UI/export checks; a successful storage helper is insufficient."""
    package = executable.parent
    manifest = json.loads((package / 'webview2-runtime.json').read_text(encoding='utf-8-sig'))
    output.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_FILES:
        (output / name).unlink(missing_ok=True)
    process = subprocess.Popen([str(executable), '--verify-native', str(output)], env=environment)
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
    for check in CHECKS + STORAGE_CHECKS:
        if report.get(check) is not True:
            raise AssertionError(f'Windows desktop check failed: {check}; {report.get("error", "no detail")}')
    if result != 0:
        raise RuntimeError(f'Windows desktop verification exited with status {result}')
    assert report.get('passed') is True, 'Native verification did not finish successfully'
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
    if environment.get('JIJI_OFFLINE_PROBE_ADDRESS'):
        assert report.get('outboundProbeBlocked') is True, 'The application outbound firewall probe was not blocked'
    diagnostics = json.loads((output / 'native-startup-diagnostic.json').read_text(encoding='utf-8'))
    assert diagnostics['schemaVersion'] == 1 and diagnostics['stage'] == 'profile-directory'
    expected_version = (Path(__file__).resolve().parents[1] / 'VERSION').read_text().strip() + '.0'
    assert diagnostics.get('applicationVersion') == expected_version, 'The running native host is not the intended release version'
    # Overlay packages deliberately retain the backend's original VERSION file;
    # this evidence comes from the executing host assembly instead.
    report['applicationVersion'] = diagnostics['applicationVersion']
    assert diagnostics['storage'] == 'temporary', 'Diagnostic writing did not fall back from an inaccessible directory'
    assert diagnostics['profileWritable'] is False
    assert diagnostics['operatingSystem']['source'] == 'RtlGetVersion', 'OS build was not read from the actual Windows kernel'
    assert diagnostics['operatingSystem']['build'] > 0
    assert diagnostics['processArchitecture'] == 'X64'
    assert diagnostics['components']['webview2/msedgewebview2.exe']['exists'] is True
    assert diagnostics['components']['webview2/msedgewebview2.exe']['productVersion'] == manifest['version']
    assert [error['type'] for error in diagnostics['exceptions']] == [
        'System.InvalidOperationException', 'System.ComponentModel.Win32Exception']
    assert diagnostics['exceptions'][1]['nativeErrorCode'] == 5
    assert all(re.fullmatch(r'0x[0-9A-F]{8}', error['hResult']) for error in diagnostics['exceptions'])
    verify_diagnostic_privacy(diagnostics)
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
    return report


def current_user_sid():
    identity = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], check=True,
                              capture_output=True, encoding='utf-8', errors='replace')
    matches = re.findall(r'S-1-\d+(?:-\d+)+', identity.stdout)
    assert len(matches) == 1, 'Could not determine the current Windows user SID'
    return matches[0]


def acl_command(*arguments):
    result = subprocess.run(['icacls', *map(str, arguments)], capture_output=True,
                            encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'Windows ACL command failed ({result.returncode}): {result.stderr.strip()}')


def assert_write_denied(directory):
    """Prove the same account running the editor gets actual ERROR_ACCESS_DENIED."""
    for operation in ('file', 'directory'):
        probe = directory / ('must-be-denied-' + operation)
        try:
            if operation == 'file':
                probe.write_bytes(b'ACL verification')
            else:
                probe.mkdir()
        except PermissionError as error:
            # Python's file-open CRT path keeps EACCES but may omit winerror;
            # mkdir uses the Win32 path and normally supplies ERROR_ACCESS_DENIED.
            assert error.winerror == 5 or (error.winerror is None and error.errno == errno.EACCES), \
                f'Expected access denied, got winerror={error.winerror}, errno={error.errno}'
        else:
            if operation == 'file':
                probe.unlink()
            else:
                probe.rmdir()
            raise AssertionError(f'The current user could still create a {operation} in the denied directory')


@contextmanager
def denied_storage_fixture(output_parent):
    """Only modify newly created test directories, then remove our exact deny ACEs."""
    sid = current_user_sid()
    fixture = output_parent / ('native-storage-fixture-' + uuid.uuid4().hex)
    fixture.mkdir()
    primary, temporary, fallback = (fixture / name for name in ('denied-data', 'denied-temp', 'writable-data'))
    denied = []
    try:
        for directory in (primary, temporary):
            directory.mkdir()
            denied.append(directory)
            # Match an otherwise valid private data directory, so the fallback is
            # triggered by the write denial rather than by a broadly readable ACL.
            acl_command(directory, '/inheritance:r', '/grant:r',
                        f'*{sid}:(OI)(CI)(F)', '*S-1-5-18:(OI)(CI)(F)', '/q')
            # W denies file/directory creation and data/attribute writes. It does not
            # deny reading the ACL or changing it during cleanup. No elevation needed.
            acl_command(directory, '/deny', f'*{sid}:(OI)(CI)(W)', '/q')
            assert_write_denied(directory)
        yield primary, temporary, fallback
    finally:
        original_error = sys.exc_info()[1]
        cleanup_errors = []
        for directory in denied:
            try:
                acl_command(directory, '/remove:d', f'*{sid}', '/q')
            except Exception as error:
                cleanup_errors.append(error)
        for attempt in range(10):
            try:
                shutil.rmtree(fixture)
                break
            except OSError as error:
                if attempt == 9:
                    cleanup_errors.append(error)
                    break
                time.sleep(0.5)
        if cleanup_errors:
            detail = 'ACL fixture cleanup failed: ' + '; '.join(str(error) for error in cleanup_errors)
            if original_error is not None:
                original_error.add_note(detail)
            else:
                raise RuntimeError(detail) from cleanup_errors[0]


# This deliberately substitutes only LibreOffice. The published Python engine
# must still create its own tempfile input, launch this process, and read its PDF.
# It proves storage placement, not the correctness of a real Office conversion.
STORAGE_CONVERTER = r'''
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import url2pathname

arguments = sys.argv[1:]
data_root = Path(os.environ['JIJI_STORAGE_EXPECTED_ROOT']).resolve()
temporary = data_root / 'Temp'
source = Path(arguments[-1]).resolve()
destination = Path(arguments[arguments.index('--outdir') + 1]).resolve()
profile_argument = next(value for value in arguments if value.startswith('-env:UserInstallation='))
profile = Path(url2pathname(urlsplit(profile_argument.split('=', 1)[1]).path)).resolve()
assert source.parent.parent == temporary and source.parent.name.startswith('jiji-convert-')
assert source.name == 'input.docx' and source.read_bytes() == b'JIJI_STORAGE_PROBE_INPUT'
assert destination == source.parent / 'converted' and destination.is_dir()
assert profile == source.parent / 'profile'
assert Path(tempfile.gettempdir()).resolve() == temporary
for name in ('TEMP', 'TMP', 'TMPDIR'):
    assert Path(os.environ[name]).resolve() == temporary
profile.mkdir()
(profile / 'write-probe').write_bytes(b'Storage verifier')
assert (profile / 'write-probe').read_bytes() == b'Storage verifier'
pdf = destination / 'input.pdf'
shutil.copyfile(os.environ['JIJI_STORAGE_PROBE_PDF'], pdf)
assert pdf.read_bytes().startswith(b'%PDF-')
evidence = {
    'passed': True, 'syntheticConverter': True, 'originalBackendTempfileUsed': True,
    'sourceUnderFallbackTemp': True, 'sourceContentVerified': True,
    'converterProfileUnderFallbackTemp': True, 'inheritedTempMatches': True,
    'outputUnderFallbackTemp': True,
    'temporaryDirectoryRelative': source.parent.relative_to(data_root).as_posix(),
}
Path(os.environ['JIJI_STORAGE_PROBE_REPORT']).write_text(json.dumps(evidence, indent=2), encoding='utf-8')
'''


def storage_converter_environment(fixture, fallback, output):
    helper = fixture / 'storage-converter.py'
    helper.write_text(STORAGE_CONVERTER, encoding='utf-8')
    command = fixture / 'storage-converter.cmd'
    command.write_bytes(b'@"%JIJI_STORAGE_PROBE_PYTHON%" -I -S "%JIJI_STORAGE_PROBE_HELPER%" %*\r\n')
    pdf = fixture / 'storage-probe.pdf'
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), 'Synthetic storage verification')
        document.save(pdf)
    output.mkdir(parents=True, exist_ok=True)
    report = output / 'backend-storage-verification.json'
    report.unlink(missing_ok=True)
    return {
        'JIJI_SOFFICE': str(command),
        'JIJI_VERIFY_STORAGE_PROBE': '1',
        'JIJI_STORAGE_EXPECTED_ROOT': str(fallback),
        'JIJI_STORAGE_PROBE_PYTHON': sys.executable,
        'JIJI_STORAGE_PROBE_HELPER': str(helper),
        'JIJI_STORAGE_PROBE_PDF': str(pdf),
        'JIJI_STORAGE_PROBE_REPORT': str(report),
    }


def verify_acl_fallback(executable, output, environment):
    with denied_storage_fixture(output.parent) as (primary, temporary, fallback):
        denied_environment = environment.copy()
        denied_environment.update({
            'JIJI_VERIFY_DATA_ROOT': str(primary),
            'JIJI_VERIFY_FALLBACK_ROOT': str(fallback),
            'TEMP': str(temporary), 'TMP': str(temporary), 'TMPDIR': str(temporary),
        })
        denied_environment.update(storage_converter_environment(primary.parent, fallback, output))
        report = verify_run(executable, output, denied_environment)
        assert report.get('dataRootFallback') is True, 'The denied data root did not select the fallback'
        assert report.get('dataRootKind') == 'application-directory', 'Unexpected fallback selection'
        assert report.get('backendStorageProbe') is True, 'The native UI did not import the synthetic storage probe'
        # The app must leave the denied directories alone, rather than repair ACLs.
        assert_write_denied(primary)
        assert_write_denied(temporary)
        assert not list(primary.iterdir()), 'The application wrote to the denied primary root'
        assert not list(temporary.iterdir()), 'The application wrote to the denied system temp root'
        assert fallback.is_dir(), 'The fallback root was not created'
        for field in ('profileDataRelative', 'sessionDataRelative', 'backendTempRelative'):
            relative = report.get(field)
            assert isinstance(relative, str) and relative, f'Missing storage location proof: {field}'
            location = (fallback / relative).resolve()
            assert location.is_relative_to(fallback.resolve()) and location != fallback.resolve(), \
                f'Storage escaped the selected fallback root: {field}'
        assert (fallback / report['profileDataRelative']).is_dir(), 'WebView2 did not create its fallback profile'
        backend = json.loads((output / 'backend-storage-verification.json').read_text(encoding='utf-8'))
        for field in ('passed', 'syntheticConverter', 'originalBackendTempfileUsed',
                      'sourceUnderFallbackTemp', 'sourceContentVerified', 'converterProfileUnderFallbackTemp',
                      'inheritedTempMatches', 'outputUnderFallbackTemp'):
            assert backend.get(field) is True, f'The original Python backend did not verify its fallback storage: {field}'
        verify_diagnostic_privacy(backend)
        conversion = (fallback / backend['temporaryDirectoryRelative']).resolve()
        assert conversion.is_relative_to((fallback / 'Temp').resolve()), 'Office temp directory escaped fallback storage'
        assert not conversion.exists(), 'The original Python backend did not clean up its temporary conversion directory'
        summary = {check: True for check in CHECKS + STORAGE_CHECKS}
        summary.update({'passed': True, 'defaultDataAclDenied': True, 'systemTempAclDenied': True,
                        'deniedAclsPreserved': True, 'dataRootFallback': True,
                        'applicationVersion': report['applicationVersion'],
                        'originalBackendTempfileVerified': True, 'conversionTemporaryFilesRemoved': True,
                        'syntheticConverterOnly': True})
    summary['testDirectoriesRemoved'] = True
    (output / 'acl-fallback-verification.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def main():
    if sys.platform != 'win32':
        raise SystemExit('Native desktop verification must run on Windows.')
    executable = Path(sys.argv[1]).resolve()
    for required in ('coreclr.dll', 'hostfxr.dll', 'System.Private.CoreLib.dll',
                     'System.Windows.Forms.dll', 'JijiEditor.runtimeconfig.json',
                     'webview2/msedgewebview2.exe', 'webview2-runtime.json'):
        assert (executable.parent / required).is_file(), f'Portable package is missing {required}'
    output = Path('output/native-windows').resolve()
    Path('output/native-windows-verification.json').unlink(missing_ok=True)
    if output.exists():
        shutil.rmtree(output)
    environment = os.environ.copy()
    for name in ('JIJI_VERIFY_DATA_ROOT', 'JIJI_VERIFY_FALLBACK_ROOT', 'JIJI_VERIFY_STORAGE_PROBE'):
        environment.pop(name, None)
    report = verify_run(executable, output, environment)
    acl_report = verify_acl_fallback(executable, output / 'permission-fallback', environment)
    summary = {check: True for check in CHECKS + STORAGE_CHECKS}
    summary['applicationVersion'] = report['applicationVersion']
    summary['dotnetRuntimeVersion'] = report['dotnetRuntimeVersion']
    summary['webView2RuntimeVersion'] = report['webView2RuntimeVersion']
    if 'outboundProbeBlocked' in report:
        summary['outboundProbeBlocked'] = report['outboundProbeBlocked']
    summary['aclDeniedFallback'] = acl_report['passed']
    summary['originalBackendTempfileVerified'] = acl_report['originalBackendTempfileVerified']
    summary['passed'] = True
    Path('output/native-windows-verification.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
