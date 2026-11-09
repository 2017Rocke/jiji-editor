"""Windows desktop launcher. The PDF editor opens in a local browser."""
import queue
import sys
import threading

from jiji.browser_launch import BrowserLaunchError, open_editor
from server import LocalServer, main as server_main


class Launcher:
    def __init__(self, root, service, opener=open_editor):
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.root = root
        self.service = service
        self.opener = opener
        self.url = service.origin + "/#token=" + service.token
        self.results = queue.Queue()
        self.opening = False
        self.closed = False
        self.messagebox = messagebox
        self.status = tk.StringVar(value="正在准备打开编辑器…")
        root.title("吉吉编辑软件")
        root.geometry("520x490")
        root.resizable(False, False)
        root.configure(bg="#f3f1e9")
        tk.Label(root, text="吉吉文档工坊", font=("Microsoft YaHei UI", 24, "bold"),
                 bg="#f3f1e9", fg="#2e493b").pack(pady=(26, 10))
        tk.Label(root, text="免费编辑 · 没有水印 · 文件留在电脑", font=("Microsoft YaHei UI", 11),
                 bg="#f3f1e9", fg="#76806c").pack()
        tk.Label(root, text="编辑期间请保持这个窗口开启。", font=("Microsoft YaHei UI", 10),
                 bg="#f3f1e9", fg="#7c8176").pack(pady=(16, 10))
        self.browsers = {"系统默认浏览器": "default", "Microsoft Edge": "edge",
                         "Google Chrome": "chrome", "Firefox": "firefox"}
        self.browser = ttk.Combobox(root, values=list(self.browsers), state="readonly", width=26)
        self.browser.current(0)
        self.browser.pack(pady=(0, 10))
        self.open_button = tk.Button(root, text="打开编辑器", command=self.open_browser,
                                     bg="#2e493b", fg="white", activebackground="#e8dfca",
                                     font=("Microsoft YaHei UI", 12), relief="flat", width=22, pady=9)
        self.open_button.pack()
        tk.Label(root, textvariable=self.status, wraplength=460, justify="center", height=3,
                 font=("Microsoft YaHei UI", 10), bg="#f3f1e9", fg="#7c8176").pack(pady=(10, 4))
        tk.Label(root, text="没有打开页面？可换一个浏览器，或复制下方地址手动打开。",
                 font=("Microsoft YaHei UI", 9), bg="#f3f1e9", fg="#7c8176").pack(pady=(0, 8))
        self.address = tk.StringVar(value=self.url)
        tk.Entry(root, textvariable=self.address, state="readonly", width=61,
                 readonlybackground="#ffffff", font=("Segoe UI", 9)).pack(padx=24, fill="x")
        self.copy_button = tk.Button(root, text="复制编辑器地址", command=self.copy_address,
                                     font=("Microsoft YaHei UI", 10), bg="#f3f1e9", fg="#2e493b")
        self.copy_button.pack(pady=(10, 4))
        tk.Button(root, text="退出软件", command=self.close, relief="flat", bg="#f3f1e9",
                  fg="#829078", font=("Microsoft YaHei UI", 10)).pack(pady=4)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll_browser)

    def open_browser(self):
        if self.opening or self.closed:
            return
        self.opening = True
        self.open_button.configure(state="disabled")
        self.status.set("正在请求浏览器打开；也可以复制下方地址手动打开。")
        browser = self.browsers[self.browser.get()]

        def launch():
            try:
                name = self.opener(self.url, browser)
                self.results.put(f"已请求 {name} 打开。若未出现页面，请更换浏览器或复制地址。")
            except BrowserLaunchError as error:
                self.results.put(str(error))
            except Exception:
                self.results.put("浏览器未能启动。请选择其他浏览器，或复制下方地址手动打开。")

        threading.Thread(target=launch, daemon=True).start()

    def poll_browser(self):
        if self.closed:
            return
        try:
            self.status.set(self.results.get_nowait())
            self.opening = False
            self.open_button.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self.poll_browser)

    def copy_address(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url)
        self.status.set("地址已复制。请在 Edge、Chrome 或 Firefox 地址栏粘贴并打开。")

    def close(self):
        if self.service.workspace.dirty and not self.messagebox.askokcancel(
                "退出吉吉", "请确认已导出 PDF。退出会丢失当前会话中尚未保存的修改。", parent=self.root):
            return
        self.closed = True
        self.service.shutdown()
        self.service.server_close()
        self.root.destroy()


def main():
    if "--no-browser" in sys.argv:
        server_main()
        return
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    try:
        service = LocalServer()
    except OSError:
        messagebox.showerror("无法启动", "本机服务启动失败，请关闭后重试。", parent=root)
        root.destroy()
        return
    worker = threading.Thread(target=service.serve_forever, daemon=True)
    worker.start()
    verifying = "--verify-launcher" in sys.argv

    def unavailable_browser(url, browser):
        raise BrowserLaunchError("无法打开浏览器，请复制下方地址手动打开。")

    launcher = Launcher(root, service, opener=unavailable_browser if verifying else open_editor)
    if verifying:
        import json
        from pathlib import Path
        output = Path(sys.argv[sys.argv.index("--verify-launcher") + 1])

        def verify():
            if launcher.opening:
                root.after(100, verify)
                return
            failure_hint = launcher.status.get() == "无法打开浏览器，请复制下方地址手动打开。"
            launcher.copy_button.invoke()
            report = {"ready": worker.is_alive(), "tk": bool(root.winfo_exists()),
                      "copyAddress": root.clipboard_get() == launcher.url,
                      "browserFailureHint": failure_hint,
                      "manualAddress": launcher.address.get() == launcher.url}
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report), encoding="utf-8")
            launcher.close()

        def start_verification():
            launcher.open_button.invoke()
            root.after(100, verify)

        root.after(350, start_verification)
    else:
        root.after(350, launcher.open_browser)
    root.mainloop()


if __name__ == "__main__":
    main()
