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
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_RUNTIME_MANIFEST = ROOT / "scripts/windows-runtime.json"


def verify_microsoft_authenticode(binary):
    """Use one PowerShell edition's own security module; never bypass a failed signature."""
    powershell = shutil.which("pwsh") or shutil.which("powershell.exe")
    if not powershell:
        raise RuntimeError("PowerShell is required to verify the Microsoft runtime binary.")
    # A PowerShell 7 parent can leave its modules on Windows PowerShell 5.1's
    # inherited lookup path. Let the chosen host construct its own module path.
    environment = {name: value for name, value in os.environ.items()
                   if name.upper() != "PSMODULEPATH"}
    environment["JIJI_MICROSOFT_BINARY"] = str(Path(binary).resolve())
    check_signature = r'''
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Security/Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
$signature = Microsoft.PowerShell.Security\Get-AuthenticodeSignature -LiteralPath $env:JIJI_MICROSOFT_BINARY
if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate) {
    throw 'The Microsoft runtime binary does not have a valid Authenticode signature.'
}
$subject = $signature.SignerCertificate.Subject
if ($subject -notmatch '(^|,\s*)CN=Microsoft Corporation(,|$)' -or
    $subject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)') {
    throw 'The runtime binary is not signed by Microsoft Corporation.'
}
Write-Output "Verified Microsoft runtime Authenticode signature."
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


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bundle_fixed_webview2(target):
    """Pin and verify the entire official CAB; no end-user downloads or installers."""
    manifest = json.loads(WINDOWS_RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    if manifest["architecture"] != "x64":
        raise RuntimeError("The Windows package requires the x64 Fixed WebView2 Runtime.")
    url = manifest["url"]
    if not url.startswith("https://msedge.sf.dl.delivery.mp.microsoft.com/"):
        raise RuntimeError("The Fixed Runtime must come directly from Microsoft's download service.")
    cache = ROOT / "build/runtime-cache"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / url.rsplit("/", 1)[-1]
    if not (archive.is_file() and archive.stat().st_size == manifest["sizeBytes"]
            and file_sha256(archive) == manifest["sha256"]):
        temporary = archive.with_suffix(".download")
        try:
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as output:
                if not response.geturl().startswith("https://"):
                    raise RuntimeError("Microsoft runtime download must remain on HTTPS.")
                shutil.copyfileobj(response, output)
            if temporary.stat().st_size != manifest["sizeBytes"] or file_sha256(temporary) != manifest["sha256"]:
                raise RuntimeError("The Fixed WebView2 Runtime does not match its pinned size/SHA-256.")
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    with archive.open("rb") as source:
        if source.read(4) != b"MSCF":
            raise RuntimeError("The pinned WebView2 Runtime is not a Windows cabinet archive.")
    with tempfile.TemporaryDirectory(prefix="webview2-", dir=ROOT / "build") as temporary:
        subprocess.run(["expand.exe", "-F:*", str(archive), temporary], check=True, stdout=subprocess.DEVNULL)
        binaries = list(Path(temporary).rglob("msedgewebview2.exe"))
        if len(binaries) != 1:
            raise RuntimeError("The Fixed Runtime CAB must contain exactly one msedgewebview2.exe.")
        with binaries[0].open("rb") as source:
            header = source.read(64)
            if len(header) != 64 or header[:2] != b"MZ":
                raise RuntimeError("The Fixed Runtime does not contain a PE executable.")
            source.seek(struct.unpack_from("<I", header, 60)[0])
            if source.read(6) != b"PE\0\0\x64\x86":
                raise RuntimeError("The Fixed Runtime executable must use the x64 architecture.")
        verify_microsoft_authenticode(binaries[0])
        # Keep every binary, data file, locale, built-in notice and license.
        shutil.copytree(binaries[0].parent, Path(target) / "webview2")
    license_source = ROOT / "scripts/windows-native/licenses/WebView2-Fixed-Runtime-LICENSE.html"
    if file_sha256(license_source) != manifest["license"]["sha256"]:
        raise RuntimeError("The bundled official WebView2 Fixed Runtime license has changed.")
    license_target = Path(target) / manifest["license"]["path"]
    license_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(license_source, license_target)
    shutil.copy2(WINDOWS_RUNTIME_MANIFEST, Path(target) / "webview2-runtime.json")
    return manifest


def bundle_dotnet_licenses(target, assets):
    """Collect the exact .NET runtime packs selected by self-contained publish."""
    runtime = json.loads((target / "JijiEditor.runtimeconfig.json").read_text(encoding="utf-8"))
    frameworks = runtime["runtimeOptions"].get("includedFrameworks", [])
    expected = {"Microsoft.NETCore.App", "Microsoft.WindowsDesktop.App"}
    if {item["name"] for item in frameworks} != expected:
        raise RuntimeError("The native editor must include both .NET and Windows Desktop runtimes.")
    dependencies = {}
    for framework in frameworks:
        name, version = framework["name"], framework["version"]
        package_name = name + ".Runtime.win-x64"
        locations = [Path(folder) / package_name.lower() / version for folder in assets["packageFolders"]]
        package = next((folder for folder in locations if folder.is_dir()), None)
        if package is None:
            raise RuntimeError(f"The restored {package_name} {version} runtime package was not found.")
        files = [path for path in package.iterdir() if path.is_file()
                 and any(word in path.name.lower() for word in ["license", "third-party", "thirdparty"]) ]
        if not any("license" in path.name.lower() for path in files):
            raise RuntimeError(f"The original {package_name} license is missing.")
        destination = target / "licenses" / package_name
        destination.mkdir(parents=True, exist_ok=True)
        for path in files:
            shutil.copy2(path, destination / path.name)
        dependencies[name] = {
            "version": version,
            "package": f"https://www.nuget.org/packages/{package_name}/{version}",
            "licenses": destination.relative_to(target).as_posix(),
            "distribution": "Self-contained win-x64; included in this application",
        }
    return dependencies


def windows_native_resources(target, assets_file):
    """Preserve SDK/runtime licenses and bundle all local Windows dependencies."""
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

    dependencies_path = target / "DEPENDENCIES.json"
    dependencies = json.loads(dependencies_path.read_text(encoding="utf-8"))
    dependencies["Microsoft.Web.WebView2"] = {
        "version": package_name.split("/", 1)[1],
        "package": "https://www.nuget.org/packages/" + package_name,
        "license": "licenses/Microsoft.Web.WebView2/LICENSE.txt",
        "notices": "licenses/Microsoft.Web.WebView2/NOTICE.txt",
    }
    dependencies.update(bundle_dotnet_licenses(target, assets))
    manifest = bundle_fixed_webview2(target)
    dependencies["Microsoft WebView2 Fixed Runtime"] = {
        "version": manifest["version"],
        "download": manifest["url"],
        "sha256": manifest["sha256"],
        "signature": "Valid Authenticode; Microsoft Corporation",
        "distribution": "Fixed x64; included in webview2/ and updated with this application",
        "license": manifest["license"]["path"],
        "thirdPartyNotices": "webview2/show_third_party_software_licenses.bat and embedded runtime resources",
        "officialInformation": "https://developer.microsoft.com/microsoft-edge/webview2/",
    }
    dependencies_path.write_text(json.dumps(dependencies, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import sys
    release_resources(sys.argv[1])
