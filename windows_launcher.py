"""Windows desktop launcher. The PDF editor opens in the default local browser."""
import sys
import threading
import webbrowser

from server import LocalServer, main as server_main


def main():
    # Headless mode lets CI verify the exact executable shipped to users.
    if "--no-browser" in sys.argv:
        server_main()
        return
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("吉吉编辑软件")
    root.geometry("480x330")
    root.resizable(False, False)
    root.configure(bg="#f3f1e9")
    try:
        service = LocalServer()
    except OSError:
        messagebox.showerror("无法启动", "本机服务启动失败，请关闭后重试。")
        root.destroy()
        return
    url = service.origin + "/#token=" + service.token
    worker = threading.Thread(target=service.serve_forever, daemon=True)
    worker.start()
    if "--verify-launcher" in sys.argv:
        import json
        from pathlib import Path
        output = Path(sys.argv[sys.argv.index("--verify-launcher") + 1])
        def verify():
            output.write_text(json.dumps({"ready": worker.is_alive(), "tk": bool(root.winfo_exists())}), encoding="utf-8")
            service.shutdown()
            service.server_close()
            root.destroy()
        root.after(300, verify)
    tk.Label(root, text="吉吉文档工坊", font=("Microsoft YaHei UI", 24, "bold"), bg="#f3f1e9", fg="#2e493b").pack(pady=(35, 12))
    tk.Label(root, text="免费编辑 · 没有水印 · 文件留在电脑", font=("Microsoft YaHei UI", 11), bg="#f3f1e9", fg="#76806c").pack()
    tk.Label(root, text="编辑器会在默认浏览器中打开。\n这个窗口保持运行即可，不需要联网。", justify="center", font=("Microsoft YaHei UI", 10), bg="#f3f1e9", fg="#7c8176").pack(pady=20)
    tk.Button(root, text="打开编辑器", command=lambda: webbrowser.open(url), bg="#2e493b", fg="white", activebackground="#e8dfca", font=("Microsoft YaHei UI", 12), relief="flat", width=20, pady=9).pack()

    def close():
        if service.workspace.dirty and not messagebox.askokcancel("退出吉吉", "请确认已导出 PDF。退出会丢失当前会话中尚未保存的修改。", parent=root):
            return
        service.shutdown()
        service.server_close()
        root.destroy()

    tk.Button(root, text="退出软件", command=close, relief="flat", bg="#f3f1e9", fg="#829078", font=("Microsoft YaHei UI", 10)).pack(pady=12)
    root.protocol("WM_DELETE_WINDOW", close)
    if "--verify-launcher" not in sys.argv:
        root.after(350, lambda: webbrowser.open(url))
    root.mainloop()


if __name__ == "__main__":
    main()
