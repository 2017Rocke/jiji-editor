import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch

from jiji import browser_launch
from jiji.browser_launch import BrowserLaunchError, open_editor


class BrowserLaunchTests(unittest.TestCase):
    URL = "http://127.0.0.1:34567/#token=private-test-session&extra=value"

    def setUp(self):
        # Tests must never invoke a real browser or depend on installed software.
        self.default = self.enterContext(patch.object(browser_launch.webbrowser, "open", return_value=False))
        self.find = self.enterContext(patch.object(browser_launch, "_find_browser", return_value=None))
        self.popen = self.enterContext(patch.object(browser_launch.subprocess, "Popen"))
        self.enterContext(patch.object(browser_launch.sys, "frozen", False, create=True))

    def test_default_success_does_not_launch_another_browser(self):
        self.default.return_value = True
        self.assertEqual(open_editor(self.URL), "默认浏览器")
        self.default.assert_called_once_with(self.URL, new=2)
        self.find.assert_not_called()
        self.popen.assert_not_called()

    def test_default_false_falls_back_to_edge(self):
        self.find.side_effect = lambda choice: "C:/Program Files/Microsoft/Edge/Application/msedge.exe" if choice == "edge" else None
        self.assertEqual(open_editor(self.URL), "Microsoft Edge")
        self.find.assert_called_once_with("edge")
        self.popen.assert_called_once()

    def test_default_exception_still_falls_back(self):
        self.default.side_effect = OSError("broken browser registration")
        self.find.side_effect = [None, "C:/Chrome/chrome.exe"]
        self.assertEqual(open_editor(self.URL), "Google Chrome")
        self.assertEqual(self.find.call_args_list, [call("edge"), call("chrome")])

    def test_fallback_continues_when_installed_browser_cannot_start(self):
        self.find.side_effect = ["C:/Edge/msedge.exe", "C:/Chrome/chrome.exe"]
        self.popen.side_effect = [OSError("permission denied"), object()]
        self.assertEqual(open_editor(self.URL), "Google Chrome")
        self.assertEqual(self.popen.call_count, 2)

    def test_explicit_missing_browser_does_not_use_default_or_other_browsers(self):
        with self.assertRaisesRegex(BrowserLaunchError, "Microsoft Edge.*复制编辑器地址"):
            open_editor(self.URL, "edge")
        self.default.assert_not_called()
        self.find.assert_called_once_with("edge")
        self.popen.assert_not_called()

    def test_no_available_browser_gives_manual_open_guidance(self):
        with self.assertRaisesRegex(BrowserLaunchError, "复制编辑器地址") as caught:
            open_editor(self.URL)
        self.assertNotIn(self.URL, str(caught.exception))
        self.assertEqual(self.find.call_args_list, [call("edge"), call("chrome"), call("firefox")])

    def test_space_in_executable_path_and_url_are_separate_arguments(self):
        executable = "C:/Program Files/Google/Chrome/Application/chrome.exe"
        self.find.return_value = executable
        self.assertEqual(open_editor(self.URL, "chrome"), "Google Chrome")
        args, kwargs = self.popen.call_args
        self.assertEqual(args, ([executable, self.URL],))
        self.assertFalse(kwargs.get("shell", False))
        self.default.assert_not_called()

    def test_process_error_does_not_expose_session_url(self):
        self.find.return_value = "C:/Firefox/firefox.exe"
        self.popen.side_effect = OSError("failed command " + self.URL)
        with self.assertRaisesRegex(BrowserLaunchError, "Firefox.*复制编辑器地址") as caught:
            open_editor(self.URL, "firefox")
        self.assertNotIn("private-test-session", str(caught.exception))

    def test_unknown_browser_has_clear_error(self):
        with self.assertRaisesRegex(BrowserLaunchError, "不支持此浏览器"):
            open_editor(self.URL, "other")
        self.default.assert_not_called()

    def test_windows_frozen_restores_original_dll_directory_after_success(self):
        self.default.return_value = True
        with patch.object(browser_launch.sys, "platform", "win32"), patch.object(browser_launch.sys, "frozen", True), patch.object(browser_launch, "_get_dll_directory", return_value="C:/custom runtime"), patch.object(browser_launch, "_set_dll_directory") as set_directory:
            self.default.side_effect = lambda *args, **kwargs: set_directory.call_args_list == [call(None)]
            self.assertEqual(open_editor(self.URL), "默认浏览器")
            self.assertEqual(set_directory.call_args_list, [call(None), call("C:/custom runtime")])

    def test_windows_frozen_restores_dll_directory_after_all_browsers_fail(self):
        self.default.side_effect = OSError("default failed")
        self.find.return_value = "C:/Browser/browser.exe"
        self.popen.side_effect = OSError("browser failed")
        with patch.object(browser_launch.sys, "platform", "win32"), patch.object(browser_launch.sys, "frozen", True), patch.object(browser_launch, "_get_dll_directory", return_value="C:/original dll path"), patch.object(browser_launch, "_set_dll_directory") as set_directory:
            with self.assertRaises(BrowserLaunchError):
                open_editor(self.URL)
            self.assertEqual(set_directory.call_args_list, [call(None), call("C:/original dll path")])

    def test_windows_frozen_attempts_restore_even_if_clear_fails(self):
        with patch.object(browser_launch.sys, "platform", "win32"), patch.object(browser_launch.sys, "frozen", True), patch.object(browser_launch, "_get_dll_directory", return_value="C:/original"), patch.object(browser_launch, "_set_dll_directory", side_effect=[OSError("clear failed"), None]) as set_directory:
            with self.assertRaisesRegex(BrowserLaunchError, "复制编辑器地址"):
                open_editor(self.URL)
            self.assertEqual(set_directory.call_args_list, [call(None), call("C:/original")])
        self.default.assert_not_called()

    def test_non_frozen_launch_does_not_change_dll_directory(self):
        self.default.return_value = True
        with patch.object(browser_launch.sys, "platform", "win32"), patch.object(browser_launch, "_get_dll_directory") as get_directory, patch.object(browser_launch, "_set_dll_directory") as set_directory:
            open_editor(self.URL)
        get_directory.assert_not_called()
        set_directory.assert_not_called()

    @unittest.skipUnless(browser_launch.sys.platform == "win32", "requires Windows DLL APIs")
    def test_native_windows_dll_directory_is_cleared_during_browser_dispatch(self):
        original = browser_launch._get_dll_directory()
        with tempfile.TemporaryDirectory(prefix="吉吉 runtime ") as directory:
            try:
                browser_launch._set_dll_directory(directory)
                observed = []

                def dispatch(*args, **kwargs):
                    observed.append(browser_launch._get_dll_directory())
                    return True

                self.default.side_effect = dispatch
                with patch.object(browser_launch.sys, "frozen", True):
                    self.assertEqual(open_editor(self.URL), "默认浏览器")
                self.assertEqual(observed, [None])
                self.assertEqual(browser_launch._get_dll_directory(), directory)
            finally:
                browser_launch._set_dll_directory(original)


class BrowserDiscoveryTests(unittest.TestCase):
    def test_finds_browser_in_each_supported_install_root(self):
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA"):
            with self.subTest(variable=variable), tempfile.TemporaryDirectory(prefix="browser with spaces ") as directory:
                executable = Path(directory, "Google", "Chrome", "Application", "chrome.exe")
                executable.parent.mkdir(parents=True)
                executable.touch()
                with patch.dict(os.environ, {variable: directory}, clear=True), patch.object(browser_launch.shutil, "which") as which:
                    self.assertEqual(browser_launch._find_browser("chrome"), str(executable))
                which.assert_not_called()

    def test_uses_path_if_common_locations_are_absent(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(browser_launch.shutil, "which", side_effect=[None, "C:/Portable Firefox/firefox.exe"]) as which:
            self.assertEqual(browser_launch._find_browser("firefox"), "C:/Portable Firefox/firefox.exe")
        self.assertEqual(which.call_args_list, [call("firefox"), call("firefox.exe")])


if __name__ == "__main__":
    unittest.main()
