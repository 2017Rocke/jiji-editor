"""Portable archive checks; no Windows processes or native GUI are executed."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_windows_startup_update import APP_FILES, build_update


class StartupUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="jiji-startup-update-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def package(self, name, base_version, host_version=None):
        package = self.root / name
        package.mkdir()
        host_version = host_version or base_version
        required = APP_FILES | {
            "NativeVerification.js", "coreclr.dll", "hostfxr.dll", "hostpolicy.dll",
            "System.Private.CoreLib.dll", "Microsoft.Web.WebView2.Core.dll",
            "Microsoft.Web.WebView2.WinForms.dll", "backend/jiji-engine.exe",
            "webview2/msedgewebview2.exe", "fr/System.Windows.Forms.resources.dll",
        }
        for filename in required:
            path = package / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("shared-runtime:" + filename).encode())
        (package / "VERSION").write_text(base_version, encoding="utf-8")
        for filename in ["JijiEditor.exe", "JijiEditor.dll", "NativeVerification.js"]:
            (package / filename).write_text(host_version + ":" + filename, encoding="utf-8")
        (package / "backend/jiji-engine.exe").write_text("engine:" + base_version, encoding="utf-8")
        self.write_json(package / "webview2-runtime.json", {"version": "157.0.4341.42", "sha256": "pinned"})
        self.write_json(package / "JijiEditor.runtimeconfig.json", {
            "runtimeOptions": {"includedFrameworks": [
                {"name": "Microsoft.NETCore.App", "version": "10.0.14"},
                {"name": "Microsoft.WindowsDesktop.App", "version": "10.0.14"},
            ]},
        })
        application = "JijiEditor/" + host_version
        self.write_json(package / "JijiEditor.deps.json", {
            "runtimeTarget": {"name": "net10.0/win-x64"},
            "libraries": {application: {"type": "project"}, "WebView2/1": {"type": "package"}},
            "targets": {"net10.0/win-x64": {
                application: {"dependencies": {"WebView2": "1"}, "runtime": {
                    "JijiEditor.dll": {"assemblyVersion": host_version + ".0"},
                }},
                "WebView2/1": {"runtime": {"Microsoft.Web.WebView2.Core.dll": {}}},
            }},
        })
        with zipfile.ZipFile(package / "Source.zip", "w") as archive:
            archive.writestr("source-version.txt", host_version)
        if base_version != host_version:
            self.write_json(package / "startup-update.json", {"expectedVersion": host_version})
            (package / "Startup-update-Source.zip").write_bytes(b"previous startup sources")
        return package

    @staticmethod
    def write_json(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def build(self, old, new, name="patch"):
        output, report = self.root / (name + ".zip"), self.root / (name + ".json")
        with contextlib.redirect_stdout(io.StringIO()):
            build_update(old, new, output, report)
        return output, json.loads(report.read_text(encoding="utf-8"))

    def test_all_supported_bases_apply_without_replacing_engines_or_original_sources(self):
        new = self.package("new", "0.3.3")
        for index, (base, host) in enumerate([("0.3.1", "0.3.1"), ("0.3.1", "0.3.2"), ("0.3.2", "0.3.2")]):
            with self.subTest(base=base, host=host):
                old = self.package("old-" + str(index), base, host)
                preserved = {name: (old / name).read_bytes() for name in [
                    "VERSION", "Source.zip", "backend/jiji-engine.exe", "webview2/msedgewebview2.exe",
                    "coreclr.dll", "Microsoft.Web.WebView2.Core.dll",
                ]}
                archive_path, report = self.build(old, new, "patch-" + str(index))
                with zipfile.ZipFile(archive_path) as archive:
                    names = set(archive.namelist())
                    self.assertEqual(names, APP_FILES | {
                        "NativeVerification.js", "Startup-update-Source.zip", "startup-update.json", "启动更新说明.txt",
                    })
                    self.assertIn("0.3.1 或 0.3.2", archive.read("启动更新说明.txt").decode("utf-8-sig"))
                    archive.extractall(old)
                for name, original in preserved.items():
                    self.assertEqual((old / name).read_bytes(), original, name)
                self.assertEqual((old / "JijiEditor.dll").read_bytes(), (new / "JijiEditor.dll").read_bytes())
                self.assertEqual((old / "Startup-update-Source.zip").read_bytes(), (new / "Source.zip").read_bytes())
                self.assertEqual(report["baseVersion"], base)
                self.assertEqual(report["expectedVersion"], "0.3.3")
                self.assertTrue(report["dependencyHashesMatch"])

    def test_one_generated_patch_can_overlay_both_complete_base_versions(self):
        old = self.package("old-31", "0.3.1")
        new = self.package("new", "0.3.3")
        archive_path, _ = self.build(old, new)
        other = self.package("old-32", "0.3.2")
        # Independently pass the same strict dependency gate for the other base.
        self.build(other, new, "validate-other-base")
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(other)
        self.assertEqual((other / "VERSION").read_text(), "0.3.2")
        self.assertEqual((other / "backend/jiji-engine.exe").read_text(), "engine:0.3.2")
        self.assertEqual((other / "JijiEditor.dll").read_text(), "0.3.3:JijiEditor.dll")

    def test_changed_runtime_dependency_is_rejected_before_archive_creation(self):
        old = self.package("old", "0.3.1")
        new = self.package("new", "0.3.3")
        for filename in ["coreclr.dll", "Microsoft.Web.WebView2.Core.dll",
                         "fr/System.Windows.Forms.resources.dll", "webview2/msedgewebview2.exe"]:
            with self.subTest(filename=filename):
                path = new / filename
                original = path.read_bytes()
                path.write_bytes(b"unexpected dependency change")
                try:
                    with self.assertRaisesRegex(RuntimeError, "changed"):
                        self.build(old, new)
                    self.assertFalse((self.root / "patch.zip").exists())
                finally:
                    path.write_bytes(original)

    def test_changed_framework_or_fixed_manifest_is_rejected(self):
        old = self.package("old", "0.3.2")
        new = self.package("new", "0.3.3")
        for filename, mutation in [
            ("JijiEditor.runtimeconfig.json", lambda data: data["runtimeOptions"]["includedFrameworks"][0].update(version="10.0.15")),
            ("webview2-runtime.json", lambda data: data.update(version="158.0.0.0")),
            ("JijiEditor.deps.json", lambda data: data["libraries"]["WebView2/1"].update(sha512="changed")),
        ]:
            with self.subTest(filename=filename):
                path = new / filename
                original = path.read_bytes()
                data = json.loads(original)
                mutation(data)
                self.write_json(path, data)
                try:
                    with self.assertRaisesRegex(RuntimeError, "changed"):
                        self.build(old, new)
                finally:
                    path.write_bytes(original)

    def test_missing_dependency_and_unsupported_base_are_rejected(self):
        old = self.package("old", "0.3.1")
        new = self.package("new", "0.3.3")
        (new / "hostfxr.dll").unlink()
        with self.assertRaisesRegex(RuntimeError, "missing hostfxr.dll"):
            self.build(old, new)
        shutil.copy2(old / "hostfxr.dll", new / "hostfxr.dll")
        (old / "VERSION").write_text("0.2.2")
        with self.assertRaisesRegex(RuntimeError, "v0.3.1/v0.3.2"):
            self.build(old, new)


if __name__ == "__main__":
    unittest.main()
