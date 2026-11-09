using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace JijiEditor
{
    internal sealed class EditorWindow : Form
    {
        private readonly WebView2 web = new WebView2 { Dock = DockStyle.Fill };
        private readonly Label loading = new Label
        {
            Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter,
            Text = "吉吉编辑软件\n\n正在准备编辑器…", Font = new Font("Microsoft YaHei UI", 16),
            BackColor = Color.FromArgb(247, 246, 239), ForeColor = Color.FromArgb(39, 72, 59)
        };
        private readonly Panel recovery = new Panel { Dock = DockStyle.Fill, Visible = false,
            BackColor = Color.FromArgb(247, 246, 239) };
        private readonly Label recoveryText = new Label { Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleCenter, Font = new Font("Microsoft YaHei UI", 14),
            ForeColor = Color.FromArgb(39, 72, 59) };
        private readonly Button recoveryExport = new Button { Text = "导出当前 PDF", Dock = DockStyle.Bottom,
            Height = 58, Font = new Font("Microsoft YaHei UI", 12) };
        private readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = 268435456 };
        private readonly string verificationDirectory;
        private readonly Dictionary<string, object> report = new Dictionary<string, object>
        {
            ["passed"] = false, ["ready"] = false, ["embeddedWebView"] = false,
            ["batchCrop"] = false, ["undo"] = false, ["pdfExport"] = false,
            ["saveCancelledKeepsDirty"] = false, ["closeGuard"] = false,
            ["recoverySaveCancelledKeepsDirty"] = false, ["recoveryPdfExport"] = false,
            ["recoveryCloseGuard"] = false
        };
        private EngineProcess engine;
        private string sessionDirectory, localOrigin, sessionToken, verificationStage = "startup";
        private bool allowClose, closePending, saving, disposed, verificationStarted;
        private bool editorReady, recovering, recoverySaved;
        private int verificationSaveMode, saveCompletions;
        private bool lastSaveResult;
        private Timer deadline;
        internal int ExitCode { get; private set; }

        internal EditorWindow(string verificationDirectory)
        {
            this.verificationDirectory = verificationDirectory;
            Text = "吉吉编辑软件";
            ClientSize = new Size(1360, 875);
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleMode = AutoScaleMode.Dpi;
            var workingArea = Screen.FromPoint(Cursor.Position).WorkingArea;
            MinimumSize = new Size(Math.Min(1020, workingArea.Width), Math.Min(720, workingArea.Height));
            Size = new Size(Math.Min(Width, workingArea.Width), Math.Min(Height, workingArea.Height));
            try { Icon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
            Controls.Add(web);
            Controls.Add(loading);
            recovery.Padding = new Padding(48);
            recovery.Controls.Add(recoveryText);
            recovery.Controls.Add(recoveryExport);
            recoveryExport.Click += async (sender, e) => await ExportRecoveryAsync();
            Controls.Add(recovery);
            loading.BringToFront();
            Shown += async (sender, e) =>
            {
                // Reapply after WinForms DPI scaling, including small laptop displays.
                var area = Screen.FromControl(this).WorkingArea;
                MinimumSize = new Size(Math.Min(1020, area.Width), Math.Min(720, area.Height));
                Size = new Size(Math.Min(Width, area.Width), Math.Min(Height, area.Height));
                Location = new Point(area.Left + (area.Width - Width) / 2, area.Top + (area.Height - Height) / 2);
                await InitializeAsync();
            };
            FormClosing += WindowClosing;
            FormClosed += (sender, e) => Shutdown();
        }

        private async Task InitializeAsync()
        {
            try
            {
                if (verificationDirectory != null)
                {
                    deadline = new Timer { Interval = 120000 };
                    deadline.Tick += (sender, e) => Fail("verification-timeout");
                    deadline.Start();
                }
                if (!await EnsureRuntimeAsync()) { Finish(false); return; }
                if (disposed) return;
                sessionDirectory = Path.Combine(Path.GetTempPath(), "jiji-session-" + Guid.NewGuid().ToString("N"));
                var security = new DirectorySecurity();
                security.SetAccessRuleProtection(true, false);
                security.AddAccessRule(new FileSystemAccessRule(WindowsIdentity.GetCurrent().User,
                    FileSystemRights.FullControl, InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                    PropagationFlags.None, AccessControlType.Allow));
                Directory.CreateDirectory(sessionDirectory, security);
                var urlFile = Path.Combine(sessionDirectory, "editor.url");
                engine = EngineProcess.Start(new[] { "--no-browser", "--url-file", urlFile });
                string url = null;
                var timeout = Stopwatch.StartNew();
                while (!disposed && timeout.ElapsedMilliseconds < 45000)
                {
                    if (engine.HasExited) throw new InvalidOperationException("编辑组件未能启动，请重新解压安装包。");
                    try { if (File.Exists(urlFile)) url = File.ReadAllText(urlFile).Trim(); } catch (IOException) { }
                    if (!string.IsNullOrWhiteSpace(url)) break;
                    await Task.Delay(100);
                }
                if (disposed) return;
                Uri uri;
                if (!Uri.TryCreate(url, UriKind.Absolute, out uri) || uri.Scheme != "http" ||
                    uri.Host != "127.0.0.1" || uri.Port < 1 || uri.UserInfo.Length != 0 ||
                    !uri.Fragment.StartsWith("#token=", StringComparison.Ordinal) || uri.Fragment.Length < 16)
                    throw new InvalidOperationException("编辑组件启动超时，请关闭软件后重试。");
                localOrigin = uri.GetLeftPart(UriPartial.Authority);
                sessionToken = Uri.UnescapeDataString(uri.Fragment.Substring("#token=".Length));
                // The URL file is only a startup handshake and contains the session secret.
                File.Delete(urlFile);
                var profile = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "JijiEditor", "WebView2");
                var environment = await WithTimeout(CoreWebView2Environment.CreateAsync(null, profile), 45000);
                if (disposed) return;
                await WithTimeout(web.EnsureCoreWebView2Async(environment), 45000);
                if (disposed) return;
                var core = web.CoreWebView2;
                core.Settings.AreDevToolsEnabled = false;
                core.Settings.AreDefaultContextMenusEnabled = false;
                core.Settings.AreBrowserAcceleratorKeysEnabled = false;
                core.Settings.IsStatusBarEnabled = false;
                core.Settings.IsZoomControlEnabled = false;
                core.Settings.IsBuiltInErrorPageEnabled = false;
                core.NavigationStarting += (sender, e) => { if (!IsLocal(e.Uri)) e.Cancel = true; };
                core.NewWindowRequested += (sender, e) => { e.Handled = true; };
                core.DownloadStarting += (sender, e) => { e.Cancel = true; };
                core.PermissionRequested += (sender, e) => { e.State = CoreWebView2PermissionState.Deny; };
                core.WebMessageReceived += SaveMessageReceived;
                core.NavigationCompleted += async (sender, e) =>
                {
                    if (disposed || recovering) return;
                    if (!e.IsSuccess)
                    {
                        if (verificationDirectory == null && editorReady) ShowRecovery();
                        else Fail("editor-navigation");
                        return;
                    }
                    editorReady = true;
                    loading.Hide();
                    if (verificationDirectory != null && !verificationStarted)
                    {
                        verificationStarted = true;
                        await VerifyAsync();
                    }
                };
                core.ProcessFailed += (sender, e) =>
                {
                    if (disposed) return;
                    if (verificationDirectory != null) { Fail("editor-process"); return; }
                    // WebView2 restarts GPU/utility/frame child processes itself. Keep the
                    // document service alive even if the main browser/renderer is lost.
                    if (e.ProcessFailedKind == CoreWebView2ProcessFailedKind.BrowserProcessExited ||
                        e.ProcessFailedKind == CoreWebView2ProcessFailedKind.RenderProcessExited ||
                        e.ProcessFailedKind == CoreWebView2ProcessFailedKind.RenderProcessUnresponsive)
                        ShowRecovery();
                };
                core.Navigate(url);
            }
            catch (Exception exception)
            {
                if (!disposed && !recovering) Fail("initialization", exception);
            }
        }

        private void ShowRecovery()
        {
            if (disposed || recovering) return;
            recovering = true;
            recoverySaved = false;
            web.Hide();
            loading.Hide();
            recoveryText.Text = "编辑窗口暂时无法显示。\n\n文档仍保留在当前会话中，请先导出 PDF 保存。\n\n保存后可以关闭并重新打开吉吉编辑软件。";
            recovery.Show();
            recovery.BringToFront();
        }

        private async Task ExportRecoveryAsync()
        {
            if (disposed || !recovering || saving) return;
            saving = true;
            recoveryExport.Enabled = false;
            try
            {
                // This path deliberately does not use the failed renderer or a JS callback.
                byte[] bytes;
                using (var client = new RecoveryPdfClient())
                {
                    client.Headers["X-Jiji-Token"] = sessionToken;
                    bytes = await WithTimeout(client.DownloadDataTaskAsync(new Uri(localOrigin + "/api/export")), 30000);
                }
                if (bytes.Length < 8 || Encoding.ASCII.GetString(bytes, 0, 5) != "%PDF-")
                    throw new InvalidDataException();
                var destination = ChooseSavePath("吉吉编辑_恢复文档.pdf");
                if (destination == null) return;
                await Task.Run(() => SavePdfAtomically(destination, bytes));
                recoverySaved = true;
                recoveryText.Text = "PDF 已保存。\n\n现在可以关闭并重新打开吉吉编辑软件，再打开刚才保存的 PDF。";
            }
            catch (Exception exception)
            {
                if (verificationDirectory != null) Fail("recovery-export", exception);
                else if (!disposed) MessageBox.Show(this,
                    "PDF 未能保存。请确认已经打开文档，并检查保存位置的权限和可用空间后重试。\n\n当前会话仍保留，请暂时不要关闭软件。",
                    Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            finally
            {
                saving = false;
                if (!disposed) recoveryExport.Enabled = true;
            }
        }

        private sealed class RecoveryPdfClient : WebClient
        {
            internal RecoveryPdfClient() { Proxy = null; }
            protected override WebRequest GetWebRequest(Uri address)
            {
                var request = (HttpWebRequest)base.GetWebRequest(address);
                request.AllowAutoRedirect = false;
                request.Timeout = 30000;
                request.ReadWriteTimeout = 30000;
                return request;
            }
        }

        private async Task<bool> EnsureRuntimeAsync()
        {
            try
            {
                CoreWebView2Environment.GetAvailableBrowserVersionString();
                return true;
            }
            catch (WebView2RuntimeNotFoundException)
            {
                if (verificationDirectory != null) { Fail("webview2-runtime-missing"); return false; }
                var installer = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "WebView2Setup.exe");
                if (!File.Exists(installer) || !MicrosoftSignature.IsTrusted(installer))
                {
                    MessageBox.Show(this,
                        "电脑缺少 Microsoft Edge WebView2 运行组件。请从微软官网安装 WebView2 Runtime，或重新下载完整的吉吉安装包。安装后重新打开软件即可。",
                        Text, MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return false;
                }
                if (MessageBox.Show(this,
                    "首次使用需要安装微软 WebView2 运行组件，编辑器才能在软件窗口中显示。\n\n现在安装吗？安装需要联网，文档不会上传。",
                    Text, MessageBoxButtons.YesNo, MessageBoxIcon.Information) != DialogResult.Yes) return false;
                loading.Text = "正在安装微软运行组件…\n\n请按安装窗口提示完成安装。";
                using (var installerProcess = Process.Start(new ProcessStartInfo(installer, "/install")
                { UseShellExecute = true, WorkingDirectory = AppDomain.CurrentDomain.BaseDirectory }))
                {
                    var timeout = Stopwatch.StartNew();
                    while (!disposed && !installerProcess.HasExited && timeout.ElapsedMilliseconds < 300000)
                        await Task.Delay(250);
                }
                if (disposed) return false;
                try { CoreWebView2Environment.GetAvailableBrowserVersionString(); return true; }
                catch (WebView2RuntimeNotFoundException)
                {
                    MessageBox.Show(this, "运行组件尚未安装完成。请完成安装后重新打开吉吉编辑软件。",
                        Text, MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return false;
                }
            }
        }

        private bool IsLocal(string source)
        {
            Uri address;
            return localOrigin != null && Uri.TryCreate(source, UriKind.Absolute, out address) &&
                string.Equals(address.GetLeftPart(UriPartial.Authority), localOrigin, StringComparison.Ordinal) &&
                address.UserInfo.Length == 0;
        }

        private async void SaveMessageReceived(object sender, CoreWebView2WebMessageReceivedEventArgs e)
        {
            if (disposed || recovering || saving || !IsLocal(e.Source)) return;
            bool saved = false;
            bool saveRequest = false;
            try
            {
                var message = json.DeserializeObject(e.WebMessageAsJson) as Dictionary<string, object>;
                if (message == null || !message.ContainsKey("type") || !Equals(message["type"], "saveFile")) return;
                saveRequest = true;
                saving = true;
                object encodedValue, nameValue;
                if (!message.TryGetValue("data", out encodedValue) || !(encodedValue is string) ||
                    !message.TryGetValue("name", out nameValue) || !(nameValue is string))
                    throw new InvalidDataException();
                var encoded = (string)encodedValue;
                if (encoded.Length > 256 * 1024 * 1024) throw new InvalidDataException();
                var bytes = Convert.FromBase64String(encoded);
                if (bytes.Length < 8 || Encoding.ASCII.GetString(bytes, 0, 5) != "%PDF-")
                    throw new InvalidDataException();
                string destination = ChooseSavePath((string)nameValue);
                // Both UI and verification use the same cancel path and durable write path.
                if (destination != null)
                {
                    await Task.Run(() => SavePdfAtomically(destination, bytes));
                    saved = true;
                }
            }
            catch (Exception exception)
            {
                if (verificationDirectory != null) Fail("native-save", exception);
                else if (!disposed) MessageBox.Show(this,
                    "PDF 未能保存，请检查保存位置的权限和可用空间后重试。编辑内容仍在当前窗口中。",
                    Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            finally
            {
                if (saveRequest)
                {
                    if (!disposed && !recovering)
                    {
                        try { await web.ExecuteScriptAsync("window.jijiSaved(" + (saved ? "true" : "false") + ")"); }
                        catch { if (verificationDirectory != null) Fail("save-callback"); }
                    }
                    lastSaveResult = saved;
                    saveCompletions++;
                    saving = false;
                }
            }
        }

        private string ChooseSavePath(string requestedName)
        {
            if (verificationDirectory != null)
            {
                if (verificationSaveMode == 1) { verificationSaveMode = 0; return null; }
                if (verificationSaveMode == 2)
                {
                    verificationSaveMode = 0;
                    return Path.Combine(verificationDirectory, "native-export.pdf");
                }
                if (verificationSaveMode == 3)
                {
                    verificationSaveMode = 0;
                    return Path.Combine(verificationDirectory, "native-recovery-export.pdf");
                }
                throw new InvalidOperationException("Unexpected verification save.");
            }
            var name = Path.GetFileName(requestedName);
            foreach (var character in Path.GetInvalidFileNameChars()) name = name.Replace(character, '_');
            if (string.IsNullOrWhiteSpace(name)) name = "吉吉编辑.pdf";
            if (!name.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase)) name += ".pdf";
            using (var dialog = new SaveFileDialog
            {
                Title = "导出 PDF", Filter = "PDF 文件 (*.pdf)|*.pdf", DefaultExt = "pdf",
                AddExtension = true, OverwritePrompt = true, FileName = name, RestoreDirectory = true
            }) return dialog.ShowDialog(this) == DialogResult.OK ? dialog.FileName : null;
        }

        private static void SavePdfAtomically(string destination, byte[] bytes)
        {
            // Write alongside the destination so replacing an existing PDF is atomic.
            var temporary = Path.Combine(Path.GetDirectoryName(destination), ".jiji-" + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    output.Write(bytes, 0, bytes.Length);
                    output.Flush(true);
                }
                if (File.Exists(destination)) File.Replace(temporary, destination, null);
                else File.Move(temporary, destination);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        private async void WindowClosing(object sender, FormClosingEventArgs e)
        {
            if (allowClose) return;
            e.Cancel = true;
            if (closePending) return;
            closePending = true;
            try
            {
                if (!await CanCloseAsync(null)) return;
                // Dispose the embedded renderer directly; no second browser beforeunload prompt.
                allowClose = true;
                Close();
            }
            finally { closePending = false; }
        }

        private async Task<bool> CanCloseAsync(bool? verificationDecision)
        {
            if (saving)
            {
                if (verificationDirectory == null) MessageBox.Show(this, "正在保存 PDF，请稍候再关闭。", Text);
                return false;
            }
            if (recovering)
            {
                if (recoverySaved) return true;
                if (verificationDecision.HasValue) return verificationDecision.Value;
                return MessageBox.Show(this, "当前会话的文档尚未导出保存。关闭后无法恢复这些编辑。确定放弃并退出吗？",
                    Text, MessageBoxButtons.YesNo, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) == DialogResult.Yes;
            }
            if (web.CoreWebView2 == null || loading.Visible) return true;
            bool dirty;
            try
            {
                if (await ScriptBoolean("(typeof busy === 'boolean' && busy) || (typeof nativeExportPending === 'boolean' && nativeExportPending)"))
                {
                    if (verificationDirectory == null) MessageBox.Show(this, "正在处理文档，请稍候再关闭。", Text);
                    return false;
                }
                // Server state.dirty describes editing history; dirtyLocal also tracks successful export.
                dirty = await ScriptBoolean("typeof dirtyLocal === 'boolean' ? dirtyLocal : true");
            }
            catch { dirty = true; }
            if (!dirty) return true;
            if (verificationDecision.HasValue) return verificationDecision.Value;
            return MessageBox.Show(this, "当前编辑尚未导出保存。确定放弃这些更改并退出吗？",
                Text, MessageBoxButtons.YesNo, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) == DialogResult.Yes;
        }

        private async Task<bool> ScriptBoolean(string expression)
        {
            return string.Equals(await WithTimeout(web.ExecuteScriptAsync("Boolean(" + expression + ")"), 5000), "true", StringComparison.Ordinal);
        }

        private static async Task<T> WithTimeout<T>(Task<T> operation, int milliseconds)
        {
            if (await Task.WhenAny(operation, Task.Delay(milliseconds)) != operation) throw new TimeoutException();
            return await operation;
        }

        private static async Task WithTimeout(Task operation, int milliseconds)
        {
            if (await Task.WhenAny(operation, Task.Delay(milliseconds)) != operation) throw new TimeoutException();
            await operation;
        }

        private async Task WaitForScript(string expression, int milliseconds = 15000)
        {
            var timer = Stopwatch.StartNew();
            while (!disposed && timer.ElapsedMilliseconds < milliseconds)
            {
                if (await ScriptBoolean(expression)) return;
                await Task.Delay(100);
            }
            throw new TimeoutException();
        }

        private async Task VerifyAsync()
        {
            try
            {
                verificationStage = "ready";
                await WaitForScript("typeof api === 'function' && typeof state === 'object' && document.body.classList.contains('is-home')");
                report["ready"] = true;
                report["embeddedWebView"] = web.CoreWebView2 != null;
                await web.ExecuteScriptAsync(File.ReadAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "NativeVerification.js")));
                verificationStage = "sample";
                await web.ExecuteScriptAsync("document.getElementById('sampleBtn').click()");
                await WaitForScript("state.pages.length === 3 && !busy && document.getElementById('pageImage').naturalWidth > 0");
                verificationStage = "batch-crop";
                await web.ExecuteScriptAsync("window.jijiNativeTest.beginCrop()");
                await WaitForScript("!busy && window.jijiNativeTest.cropped()");
                report["batchCrop"] = true;
                verificationStage = "undo";
                await web.ExecuteScriptAsync("document.getElementById('undoBtn').click()");
                await WaitForScript("!busy && window.jijiNativeTest.restored()");
                report["undo"] = true;
                // Make a fresh change so cancellation and close guard have real dirty state.
                await web.ExecuteScriptAsync("document.querySelector('.tool[data-tool=select]').click(); document.getElementById('rotateBtn').click()");
                await WaitForScript("!busy && dirtyLocal");
                verificationStage = "save-cancel";
                verificationSaveMode = 1;
                var completedBefore = saveCompletions;
                await web.ExecuteScriptAsync("document.getElementById('exportBtn').click()");
                await WaitForSave(completedBefore);
                if (lastSaveResult || !await ScriptBoolean("dirtyLocal")) throw new InvalidOperationException();
                report["saveCancelledKeepsDirty"] = true;
                verificationStage = "close-guard";
                if (await CanCloseAsync(false) || !await ScriptBoolean("dirtyLocal")) throw new InvalidOperationException();
                await web.ExecuteScriptAsync("document.getElementById('rotateBtn').click()");
                await WaitForScript("!busy && dirtyLocal && window.jijiNativeTest.changedAfterClose()");
                report["closeGuard"] = true;
                verificationStage = "native-save";
                verificationSaveMode = 2;
                completedBefore = saveCompletions;
                await web.ExecuteScriptAsync("document.getElementById('exportBtn').click()");
                await WaitForSave(completedBefore);
                if (!lastSaveResult || await ScriptBoolean("dirtyLocal") || !await CanCloseAsync(false))
                    throw new InvalidOperationException();
                var pdf = File.ReadAllBytes(Path.Combine(verificationDirectory, "native-export.pdf"));
                if (pdf.Length < 1000 || Encoding.ASCII.GetString(pdf, 0, 5) != "%PDF-" ||
                    !Encoding.ASCII.GetString(pdf, Math.Max(0, pdf.Length - 1024), Math.Min(1024, pdf.Length)).Contains("%%EOF"))
                    throw new InvalidDataException();
                report["pdfExport"] = true;
                verificationStage = "screenshot";
                await WaitForScript("!busy && document.getElementById('pageImage').naturalWidth > 0");
                await Task.Delay(300);
                using (var picture = File.Create(Path.Combine(verificationDirectory, "native-window.png")))
                    await web.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, picture);
                // Keep the regular editor screenshot, then exercise recovery against a
                // genuinely newer unsaved document without depending on the renderer.
                verificationStage = "recovery-cancel";
                await web.ExecuteScriptAsync("window.__jijiRecoveryBeforeRevision = state.revision; document.getElementById('rotateBtn').click()");
                await WaitForScript("!busy && dirtyLocal && state.revision > window.__jijiRecoveryBeforeRevision");
                ShowRecovery();
                if (await CanCloseAsync(false)) throw new InvalidOperationException();
                verificationSaveMode = 1;
                await ExportRecoveryAsync();
                if (disposed) return;
                if (recoverySaved || engine.HasExited || await CanCloseAsync(false) ||
                    File.Exists(Path.Combine(verificationDirectory, "native-recovery-export.pdf")))
                    throw new InvalidOperationException();
                report["recoverySaveCancelledKeepsDirty"] = true;
                verificationStage = "recovery-save";
                verificationSaveMode = 3;
                await ExportRecoveryAsync();
                if (disposed) return;
                var recovered = File.ReadAllBytes(Path.Combine(verificationDirectory, "native-recovery-export.pdf"));
                if (!recoverySaved || engine.HasExited || recovered.Length < 1000 ||
                    Encoding.ASCII.GetString(recovered, 0, 5) != "%PDF-")
                    throw new InvalidDataException();
                report["recoveryPdfExport"] = true;
                if (!await CanCloseAsync(false)) throw new InvalidOperationException();
                report["recoveryCloseGuard"] = true;
                report["passed"] = true;
                Finish(true);
            }
            catch (Exception exception) { if (!disposed) Fail(verificationStage, exception); }
        }

        private async Task WaitForSave(int previous)
        {
            var timer = Stopwatch.StartNew();
            while (!disposed && saveCompletions == previous && timer.ElapsedMilliseconds < 15000) await Task.Delay(100);
            if (disposed || saveCompletions == previous) throw new TimeoutException();
        }

        private void Fail(string stage, Exception exception = null)
        {
            if (disposed) return;
            ExitCode = 1;
            if (verificationDirectory != null)
            {
                report["error"] = "Native verification failed: " + stage;
                if (exception != null)
                {
                    // Exception messages can contain the token-bearing local URL; never persist them.
                    report["exceptionType"] = exception.GetType().FullName;
                    report["hResult"] = "0x" + exception.HResult.ToString("X8");
                }
            }
            else MessageBox.Show(this,
                "编辑器未能正常启动或已意外停止。请完整解压最新版安装包后重试。\n\n如果问题仍然存在，请反馈 Windows 版本和此提示。",
                Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
            Finish(false);
        }

        private void Finish(bool passed)
        {
            if (disposed) return;
            if (verificationDirectory != null)
            {
                ExitCode = passed ? 0 : 1;
                try { File.WriteAllText(Path.Combine(verificationDirectory, "native-verification.json"), json.Serialize(report), new UTF8Encoding(false)); }
                catch { ExitCode = 1; }
            }
            allowClose = true;
            Close();
        }

        private void Shutdown()
        {
            if (disposed) return;
            disposed = true;
            deadline?.Stop();
            deadline?.Dispose();
            web.Dispose();
            engine?.Dispose();
            if (sessionDirectory != null)
                try { Directory.Delete(sessionDirectory, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
    }
}
