"""Reproducible release contents: source, dependency licenses, and notices."""
from importlib import metadata
from pathlib import Path
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import sysconfig
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WEBVIEW2_SETUP_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"


def verify_microsoft_authenticode(installer):
    """Use one PowerShell edition's own security module; never bypass a failed signature."""
    powershell = shutil.which("pwsh") or shutil.which("powershell.exe")
    if not powershell:
        raise RuntimeError("PowerShell is required to verify the Microsoft runtime installer.")
    # A PowerShell 7 parent can leave its modules on Windows PowerShell 5.1's
    # inherited lookup path. Let the chosen host construct its own module path.
    environment = {name: value for name, value in os.environ.items()
                   if name.upper() != "PSMODULEPATH"}
    environment["JIJI_WEBVIEW2_INSTALLER"] = str(Path(installer).resolve())
    check_signature = r'''
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Security/Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
$signature = Microsoft.PowerShell.Security\Get-AuthenticodeSignature -LiteralPath $env:JIJI_WEBVIEW2_INSTALLER
if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate) {
    throw 'The WebView2 installer does not have a valid Authenticode signature.'
}
$subject = $signature.SignerCertificate.Subject
if ($subject -notmatch '(^|,\s*)CN=Microsoft Corporation(,|$)' -or
    $subject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)') {
    throw 'The WebView2 installer is not signed by Microsoft Corporation.'
}
Write-Output "Verified Microsoft WebView2 installer signature."
'''
    subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", check_signature],
                   env=environment, check=True)


def source_archive(target):
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True)
    files = [name.decode() for name in result.stdout.split(b"\0") if name]
    if not files:
        raise RuntimeError("Stage or commit the public source files before building a release.")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            path = ROOT / name
            if path.is_file():
                archive.write(path, "jiji-editor/" + name)


def release_resources(target):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    for name in ["LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "VERSION"]:
        shutil.copy2(ROOT / name, target / name)
    source_archive(target / "Source.zip")
    licenses = target / "licenses"
    licenses.mkdir(exist_ok=True)
    for package in ["PyMuPDF", "Pillow", "pyinstaller"]:
        dist = metadata.distribution(package)
        for file in dist.files or []:
            if any(word in file.name.lower() for word in ["license", "copying", "notice"]) and ("dist-info" in str(file) or package == "pyinstaller"):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    destination = licenses / package / str(file).replace("../", "")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    # Windows and Unix CPython distributions place their PSF license differently.
    candidates = [Path(sysconfig.get_path("stdlib")) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE.txt"]
    license_file = next((p for p in candidates if p.is_file()), None)
    if license_file:
        shutil.copy2(license_file, licenses / "PYTHON-LICENSE.txt")
    else:
        raise RuntimeError("Python license not found; release must include the interpreter's license.")
    import pymupdf
    python_version = sys.version.split()[0]
    dependencies = {
        "Python": {"version": python_version, "source": f"https://github.com/python/cpython/tree/v{python_version}"},
        "PyMuPDF": {"version": pymupdf.version[0], "source": f"https://github.com/pymupdf/PyMuPDF/tree/{pymupdf.version[0]}"},
        "MuPDF": {"version": pymupdf.version[1], "source": f"https://github.com/ArtifexSoftware/mupdf/tree/{pymupdf.version[1]}"},
        "Pillow": {"version": metadata.version("Pillow"), "source": f"https://github.com/python-pillow/Pillow/tree/{metadata.version('Pillow')}"},
        "PyInstaller": {"version": metadata.version("pyinstaller"), "source": f"https://github.com/pyinstaller/pyinstaller/tree/v{metadata.version('pyinstaller')}"},
    }
    (target / "DEPENDENCIES.json").write_text(json.dumps(dependencies, indent=2) + "\n", encoding="utf-8")


def windows_native_resources(target, assets_file):
    """Keep the exact restored SDK license and verify Microsoft's runtime installer."""
    target = Path(target)
    assets = json.loads(Path(assets_file).read_text(encoding="utf-8-sig"))
    matches = [(name, info) for name, info in assets["libraries"].items()
               if name.lower().startswith("microsoft.web.webview2/")]
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one restored WebView2 SDK version.")
    package_name, package_info = matches[0]
    package_path = package_info["path"]
    locations = [Path(folder) / package_path for folder in assets["packageFolders"]]
    sdk = next((folder for folder in locations if (folder / "LICENSE.txt").is_file()), None)
    if sdk is None:
        raise RuntimeError("The official WebView2 NuGet package's LICENSE.txt is missing.")
    licenses = target / "licenses/Microsoft.Web.WebView2"
    licenses.mkdir(parents=True, exist_ok=True)
    for name in ["LICENSE.txt", "NOTICE.txt"]:
        source = sdk / name
        if not source.is_file():
            raise RuntimeError(f"The official WebView2 NuGet package's {name} is missing.")
        shutil.copy2(source, licenses / name)

    installer = target / "WebView2Setup.exe"
    temporary = installer.with_suffix(".download.exe")
    try:
        with urllib.request.urlopen(WEBVIEW2_SETUP_URL, timeout=120) as response:
            if not response.geturl().lower().startswith("https://"):
                raise RuntimeError("WebView2 download must remain on HTTPS.")
            with temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
        # Reject HTML/error pages before checking the trusted Windows signature.
        with temporary.open("rb") as source:
            header = source.read(64)
            if len(header) != 64 or header[:2] != b"MZ":
                raise RuntimeError("Microsoft's WebView2 bootstrapper is not a PE executable.")
            source.seek(struct.unpack_from("<I", header, 60)[0])
            if source.read(4) != b"PE\0\0":
                raise RuntimeError("Microsoft's WebView2 bootstrapper has an invalid PE header.")
        verify_microsoft_authenticode(temporary)
        temporary.replace(installer)
    finally:
        temporary.unlink(missing_ok=True)

    dependencies_path = target / "DEPENDENCIES.json"
    dependencies = json.loads(dependencies_path.read_text(encoding="utf-8"))
    dependencies["Microsoft.Web.WebView2"] = {
        "version": package_name.split("/", 1)[1],
        "package": "https://www.nuget.org/packages/" + package_name,
        "license": "licenses/Microsoft.Web.WebView2/LICENSE.txt",
        "notices": "licenses/Microsoft.Web.WebView2/NOTICE.txt",
    }
    dependencies["WebView2 Runtime Bootstrapper"] = {
        "download": WEBVIEW2_SETUP_URL,
        "sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
        "signature": "Valid Authenticode; Microsoft Corporation",
        "runtime": "Evergreen; independently maintained by Microsoft",
        "officialInformation": "https://developer.microsoft.com/microsoft-edge/webview2/",
    }
    dependencies_path.write_text(json.dumps(dependencies, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import sys
    release_resources(sys.argv[1])
