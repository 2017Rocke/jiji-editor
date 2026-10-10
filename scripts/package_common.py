"""Reproducible release contents: source, dependency licenses, and notices."""
from importlib import metadata
from pathlib import Path
import json
import shutil
import subprocess
import sys
import sysconfig
import zipfile

ROOT = Path(__file__).resolve().parents[1]


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


if __name__ == "__main__":
    import sys
    release_resources(sys.argv[1])
