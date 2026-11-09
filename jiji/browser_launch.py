"""Launch an external browser without inheriting PyInstaller's DLL directory."""

from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import webbrowser


class BrowserLaunchError(RuntimeError):
    """A browser could not be launched; safe to display directly to the user."""


_BROWSERS = {
    "edge": ("Microsoft Edge", ("Microsoft", "Edge", "Application", "msedge.exe"), ("msedge", "msedge.exe")),
    "chrome": ("Google Chrome", ("Google", "Chrome", "Application", "chrome.exe"), ("chrome", "chrome.exe")),
    "firefox": ("Firefox", ("Mozilla Firefox", "firefox.exe"), ("firefox", "firefox.exe")),
}
_DLL_DIRECTORY_LOCK = threading.Lock()
_MANUAL_OPEN = "请复制编辑器地址，粘贴到浏览器地址栏手动打开。"


def _kernel32():
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
    library.GetDllDirectoryW.restype = ctypes.c_uint32
    library.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
    library.SetDllDirectoryW.restype = ctypes.c_int
    return library


def _get_dll_directory():
    library = _kernel32()
    ctypes.set_last_error(0)
    size = library.GetDllDirectoryW(0, None)
    if not size:
        error = ctypes.get_last_error()
        if error:
            raise ctypes.WinError(error)
        return None
    buffer = ctypes.create_unicode_buffer(size + 1)
    ctypes.set_last_error(0)
    length = library.GetDllDirectoryW(len(buffer), buffer)
    if not length and ctypes.get_last_error():
        raise ctypes.WinError(ctypes.get_last_error())
    if length >= len(buffer):
        raise OSError("DLL directory changed while reading it")
    return buffer.value or None


def _set_dll_directory(directory):
    if not _kernel32().SetDllDirectoryW(directory):
        raise ctypes.WinError(ctypes.get_last_error())


@contextmanager
def _browser_process_environment():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        yield
        return
    # SetDllDirectory affects the entire process. Keep overlapping launch requests
    # serialized, and restore the actual previous value rather than guessing _MEIPASS.
    with _DLL_DIRECTORY_LOCK:
        previous = _get_dll_directory()
        try:
            _set_dll_directory(None)
            yield
        finally:
            _set_dll_directory(previous)


def _find_browser(browser):
    _, relative_path, commands = _BROWSERS[browser]
    for key in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA"):
        root = os.environ.get(key)
        if root:
            candidate = Path(root).joinpath(*relative_path)
            if candidate.is_file():
                return str(candidate)
    for command in commands:
        executable = shutil.which(command)
        if executable:
            return executable
    return None


def _launch_installed_browser(url, browser):
    executable = _find_browser(browser)
    if not executable:
        return False
    try:
        # Never invoke a shell: the URL (including its private session fragment)
        # remains one argument, even when the executable path contains spaces.
        subprocess.Popen(
            [executable, url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError:
        return False
    return True


def open_editor(url, browser="default"):
    """Return the browser's name after dispatch, without claiming the page loaded."""
    if browser != "default" and browser not in _BROWSERS:
        raise BrowserLaunchError("不支持此浏览器。" + _MANUAL_OPEN)
    try:
        with _browser_process_environment():
            if browser == "default":
                try:
                    if webbrowser.open(url, new=2):
                        return "默认浏览器"
                except Exception:
                    # Broken default-app registrations can raise instead of
                    # returning False. Installed browsers can still work.
                    pass
                choices = _BROWSERS
            else:
                choices = (browser,)
            for choice in choices:
                if _launch_installed_browser(url, choice):
                    return _BROWSERS[choice][0]
    except Exception:
        # Do not surface OS exceptions: they may contain the private session URL.
        raise BrowserLaunchError("浏览器启动失败。" + _MANUAL_OPEN) from None
    name = "可用的浏览器" if browser == "default" else _BROWSERS[browser][0]
    raise BrowserLaunchError("未能启动" + name + "。" + _MANUAL_OPEN)
