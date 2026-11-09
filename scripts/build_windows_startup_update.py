"""Build a small, dependency-matched startup update for an existing Windows ZIP.

This does not rebuild or replace the PDF engine, WebView2, or bundled .NET.
The generated ZIP is applied to the root of the existing application folder.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import zipfile


APP_FILES = {"JijiEditor.exe", "JijiEditor.dll", "JijiEditor.deps.json", "JijiEditor.runtimeconfig.json"}
NATIVE_EXTENSIONS = {".dll", ".exe", ".json", ".config", ".manifest", ".dat", ".bin", ".pak"}
PACKAGE_METADATA = {"DEPENDENCIES.json", "webview2-runtime.json", "startup-update.json"}


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def inventory(directory, predicate=lambda path: True):
    return {path.relative_to(directory).as_posix(): digest(path)
            for path in directory.rglob("*") if path.is_file() and predicate(path.relative_to(directory))}


def require_same(label, old, new):
    if old == new:
        return
    if isinstance(old, dict) and isinstance(new, dict):
        differences = sorted(key for key in old.keys() | new.keys() if old.get(key) != new.get(key))
        detail = ", ".join(differences[:12])
    else:
        detail = "values differ"
    raise RuntimeError(f"Cannot create a startup-only update: {label} changed ({detail}).")


def runtime_frameworks(package):
    options = read_json(package / "JijiEditor.runtimeconfig.json")["runtimeOptions"]
    frameworks = options.get("includedFrameworks", [])
    if not frameworks or options.get("framework") or options.get("frameworks"):
        raise RuntimeError("Both packages must contain self-contained .NET runtimes.")
    return {item["name"]: item["version"] for item in frameworks}


def dependency_model(package):
    model = copy.deepcopy(read_json(package / "JijiEditor.deps.json"))
    applications = [name for name, value in model["libraries"].items()
                    if name.startswith("JijiEditor/") and value.get("type") == "project"]
    if len(applications) != 1:
        raise RuntimeError("Expected exactly one JijiEditor application in the dependency manifest.")
    application = applications[0]
    del model["libraries"][application]
    for target in model["targets"].values():
        if application in target:
            entry = target.pop(application)
            # Only the main application's version/assembly metadata may change.
            model.setdefault("applicationDependencies", []).append(entry.get("dependencies", {}))
    return model


def is_native_dependency(relative):
    if relative.parts[0] in {"backend", "webview2", "licenses"}:
        return False
    name = relative.as_posix()
    return (name not in APP_FILES and name not in PACKAGE_METADATA
            and relative.suffix.lower() in NATIVE_EXTENSIONS)


def build_update(old, new, output, report_path):
    old, new = old.resolve(), new.resolve()
    if old == new or not old.is_dir() or not new.is_dir():
        raise RuntimeError("Provide two different, fully extracted Windows package directories.")
    base_version = (old / "VERSION").read_text(encoding="utf-8").strip()
    version = (new / "VERSION").read_text(encoding="utf-8").strip()
    if (base_version, version) != ("0.3.1", "0.3.2"):
        raise RuntimeError("This startup update must target a complete v0.3.1 package using v0.3.2 app files.")
    for package in (old, new):
        for name in APP_FILES | {"NativeVerification.js", "Source.zip", "webview2-runtime.json",
                                 "coreclr.dll", "hostfxr.dll", "hostpolicy.dll", "System.Private.CoreLib.dll",
                                 "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll",
                                 "backend/jiji-engine.exe", "webview2/msedgewebview2.exe"}:
            if not (package / name).is_file():
                raise RuntimeError(f"Incomplete package: missing {name}.")
    frameworks = runtime_frameworks(old)
    require_same("included .NET frameworks", frameworks, runtime_frameworks(new))
    require_same("native dependency manifest", dependency_model(old), dependency_model(new))
    require_same("Fixed WebView2 manifest", read_json(old / "webview2-runtime.json"),
                 read_json(new / "webview2-runtime.json"))
    fixed_files = inventory(old / "webview2")
    require_same("Fixed WebView2 runtime files", fixed_files, inventory(new / "webview2"))
    native_files = inventory(old, is_native_dependency)
    require_same("native publish dependency files", native_files, inventory(new, is_native_dependency))

    changed_files = sorted(APP_FILES)
    if digest(old / "NativeVerification.js") != digest(new / "NativeVerification.js"):
        changed_files.append("NativeVerification.js")
    sources = {name: name for name in changed_files}
    sources["Startup-update-Source.zip"] = "Source.zip"
    changed_files.append("Startup-update-Source.zip")
    with zipfile.ZipFile(new / "Source.zip") as source:
        if source.testzip() is not None:
            raise RuntimeError("The new package's corresponding source archive is corrupt.")
    manifest = {
        "baseVersion": base_version, "expectedVersion": version,
        "includedFrameworks": frameworks,
        "webview2Version": read_json(old / "webview2-runtime.json")["version"],
        "verifiedNativeDependencyFiles": len(native_files),
        "verifiedWebView2Files": len(fixed_files),
        "nativeDependencyInventorySha256": hashlib.sha256(
            json.dumps(native_files, sort_keys=True).encode("utf-8")).hexdigest(),
        "webview2InventorySha256": hashlib.sha256(
            json.dumps(fixed_files, sort_keys=True).encode("utf-8")).hexdigest(),
        "files": {name: {"sha256": digest(new / sources[name]), "sizeBytes": (new / sources[name]).stat().st_size}
                  for name in changed_files},
        "dependencyHashesMatch": True,
        "preserved": ["backend/", "webview2/", "VERSION", "Source.zip", "bundled .NET and WebView2 SDK dependencies"],
    }
    instructions = (
        "吉吉编辑软件 0.3.2 启动更新包\n\n"
        "适用范围：已完整解压的 Windows 64 位 v0.3.1。此文件不是完整安装包。\n\n"
        "1. 退出吉吉编辑软件。\n"
        "2. 将本 ZIP 中的全部文件解压到原来 JijiEditor.exe 所在文件夹。\n"
        "3. 出现同名文件提示时选择替换，再双击原文件夹里的 JijiEditor.exe。\n\n"
        "本次只更新启动窗口和诊断能力，不需要重新下载文档处理及显示组件。\n"
        "更新后主窗口/诊断版本为 0.3.2，编辑页面仍显示 0.3.1，属于正常情况。\n"
        "请保留原文件夹中的 backend、webview2 和所有其他文件。\n"
        "原 Source.zip 对应原编辑组件；Startup-update-Source.zip 对应本次启动更新。\n"
        "需要整体升级时，请使用新的完整安装包。\n"
        "若仍无法打开，请使用启动错误窗口提供的诊断信息反馈具体问题。\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in changed_files:
            archive.write(new / sources[name], name)
        archive.writestr("启动更新说明.txt", instructions.encode("utf-8-sig"))
        archive.writestr("startup-update.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    # Inspect the actual ZIP contents; runtime and backend files must never enter it.
    with zipfile.ZipFile(output) as archive:
        if set(archive.namelist()) != set(changed_files) | {"启动更新说明.txt", "startup-update.json"}:
            raise RuntimeError("Unexpected file in the startup update archive.")
        for name, item in manifest["files"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != item["sha256"]:
                raise RuntimeError(f"Startup ZIP verification failed for {name}.")
    report = dict(manifest, passed=True, archive=output.name, archiveSha256=digest(output),
                  archiveSizeBytes=output.stat().st_size)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_package", type=Path)
    parser.add_argument("new_package", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/JijiEditor-0.3.2-Windows-startup-update.zip"))
    parser.add_argument("--report", type=Path, default=Path("output/startup-update-verification.json"))
    args = parser.parse_args()
    build_update(args.old_package, args.new_package, args.output, args.report)


if __name__ == "__main__":
    main()
