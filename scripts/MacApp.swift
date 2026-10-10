import AppKit
import WebKit
import UniformTypeIdentifiers

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var web: WKWebView!
    var engine: Process?
    var urlFile: URL!
    var serverOrigin = ""
    var quitting = false
    var startupTimer: Timer?
    var verified = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        menu.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于吉吉编辑软件", action: #selector(about), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "退出吉吉编辑软件", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        let editItem = NSMenuItem()
        editItem.title = "编辑"
        let editMenu = NSMenu(title: "编辑")
        for (title, selector, key) in [("撤销", "undo:", "z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        editItem.submenu = editMenu
        menu.addItem(editItem)
        NSApp.mainMenu = menu
        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "saveFile")
        web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1360, height: 875), configuration: config)
        web.autoresizingMask = [.width, .height]
        web.uiDelegate = self
        web.navigationDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1360, height: 875), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "吉吉编辑软件"
        window.minSize = NSSize(width: 1020, height: 720)
        window.contentView = web
        window.delegate = self
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        web.loadHTMLString("<html><body style='background:#f5f6f2;color:#254c37;font-family:-apple-system;text-align:center;padding-top:25vh'><h1>吉吉编辑软件</h1><p>正在打开你的文档工作台…</p></body></html>", baseURL: nil)
        startEngine()
    }

    func startEngine() {
        guard let resources = Bundle.main.resourceURL else { return }
        urlFile = FileManager.default.temporaryDirectory.appendingPathComponent("jiji-\(UUID().uuidString).url")
        let process = Process()
        process.executableURL = resources.appendingPathComponent("backend/jiji-engine")
        process.arguments = ["--no-browser", "--url-file", urlFile.path]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        engine = process
        do { try process.run() } catch { fail("PDF 引擎无法启动：\(error.localizedDescription)"); return }
        var attempts = 0
        startupTimer = Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { [weak self] timer in
            guard let self = self else { timer.invalidate(); return }
            attempts += 1
            if let value = try? String(contentsOf: self.urlFile, encoding: .utf8), let url = URL(string: value), let host = url.host, host == "127.0.0.1" {
                timer.invalidate()
                self.serverOrigin = "http://127.0.0.1:\(url.port!)"
                self.web.load(URLRequest(url: url))
                try? FileManager.default.removeItem(at: self.urlFile)
            } else if attempts > 200 || !process.isRunning {
                timer.invalidate()
                self.fail("PDF 引擎启动失败，请关闭应用后重试。")
            }
        }
    }

    func fail(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "吉吉暂时无法启动"
        alert.informativeText = message
        alert.runModal()
        quitting = true
        NSApp.terminate(nil)
    }

    @objc func about() { web.evaluateJavaScript("document.getElementById('aboutDialog').showModal()", completionHandler: nil) }

    // Development smoke test exercises the shipped WebKit view and bundled engine.
    // This path is dormant during normal launches and never reads a user's files.
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        let args = ProcessInfo.processInfo.arguments
        guard !verified, let flag = args.firstIndex(of: "--verify"), flag + 1 < args.count,
              webView.url?.host == "127.0.0.1" else { return }
        verified = true
        let directory = URL(fileURLWithPath: args[flag + 1], isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let script = """
        const s = await api('/api/sample', {}); setState(s);
        for (let i=0; i<100 && !document.getElementById('pageImage').naturalWidth; i++) await new Promise(r=>setTimeout(r,100));
        const pdf = await api('/api/export');
        const data = await new Promise(resolve=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.readAsDataURL(pdf)});
        return {pages:s.pages.length, title:document.title, ready:document.getElementById('pageImage').naturalWidth>0, pdf:data};
        """
        webView.callAsyncJavaScript(script, arguments: [:], in: nil, in: .page) { result in
            switch result {
            case .success(let value):
                if var report = value as? [String: Any] {
                    if let b64 = report.removeValue(forKey: "pdf") as? String, let pdf = Data(base64Encoded: b64) { try? pdf.write(to: directory.appendingPathComponent("native-export.pdf")) }
                    if let json = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]) { try? json.write(to: directory.appendingPathComponent("native-verification.json")) }
                }
                webView.takeSnapshot(with: nil) { image, _ in
                    if let data = image?.tiffRepresentation, let bitmap = NSBitmapImageRep(data: data), let png = bitmap.representation(using: .png, properties: [:]) { try? png.write(to: directory.appendingPathComponent("native-window.png")) }
                    self.quitting = true; NSApp.terminate(nil)
                }
            case .failure(let error):
                try? error.localizedDescription.write(to: directory.appendingPathComponent("native-error.txt"), atomically: true, encoding: .utf8)
                self.quitting = true; NSApp.terminate(nil)
            }
        }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "saveFile", message.frameInfo.isMainFrame, message.frameInfo.securityOrigin.host == "127.0.0.1",
              let body = message.body as? [String: String], let encoded = body["data"], let data = Data(base64Encoded: encoded) else { return }
        let panel = NSSavePanel()
        panel.title = "导出 PDF"
        panel.nameFieldStringValue = ((body["name"] ?? "吉吉编辑.pdf") as NSString).lastPathComponent
        panel.allowedContentTypes = [.pdf]
        panel.canCreateDirectories = true
        panel.beginSheetModal(for: window) { response in
            var saved = false
            if response == .OK, let url = panel.url {
                do { try data.write(to: url, options: .atomic); saved = true }
                catch { let alert = NSAlert(); alert.messageText = "保存失败"; alert.informativeText = error.localizedDescription; alert.runModal() }
            }
            self.web.evaluateJavaScript("window.jijiSaved(\(saved ? "true" : "false"))", completionHandler: nil)
        }
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.beginSheetModal(for: window) { result in completionHandler(result == .OK ? panel.urls : nil) }
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = message; alert.addButton(withTitle: "好")
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = message; alert.addButton(withTitle: "继续"); alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: window) { response in completionHandler(response == .alertFirstButtonReturn) }
    }
    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let alert = NSAlert(); alert.messageText = prompt; alert.addButton(withTitle: "打开"); alert.addButton(withTitle: "取消")
        let field = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 260, height: 24)); alert.accessoryView = field
        alert.beginSheetModal(for: window) { response in completionHandler(response == .alertFirstButtonReturn ? field.stringValue : nil) }
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = navigationAction.request.url, url.scheme == "http" || url.scheme == "https" {
            if url.host != "127.0.0.1" { NSWorkspace.shared.open(url); decisionHandler(.cancel); return }
        }
        decisionHandler(.allow)
    }
    func confirmClose(_ completion: @escaping (Bool) -> Void) {
        web.evaluateJavaScript("typeof dirtyLocal !== 'undefined' && dirtyLocal") { result, _ in
            guard result as? Bool == true else { completion(true); return }
            let alert = NSAlert(); alert.messageText = "当前编辑尚未导出"; alert.informativeText = "关闭窗口会丢失这些编辑。请先导出 PDF 保存。"; alert.addButton(withTitle: "继续编辑"); alert.addButton(withTitle: "放弃并退出")
            alert.beginSheetModal(for: self.window) { response in completion(response == .alertSecondButtonReturn) }
        }
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if quitting { return true }
        confirmClose { should in if should { self.quitting = true; NSApp.terminate(nil) } }
        return false
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitting { return .terminateNow }
        confirmClose { should in self.quitting = should; sender.reply(toApplicationShouldTerminate: should) }
        return .terminateLater
    }
    func applicationWillTerminate(_ notification: Notification) {
        startupTimer?.invalidate()
        if engine?.isRunning == true { engine?.terminate() }
        if let url = urlFile { try? FileManager.default.removeItem(at: url) }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
