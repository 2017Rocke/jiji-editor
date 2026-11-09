using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Win32;

namespace JijiEditor
{
    internal enum StartupStage
    {
        RuntimePreparation, DotNetRuntime, RuntimeManifest, RuntimePermissions, ProfileDirectory,
        SessionDirectory, BackendStart, BackendHandshake, WebViewEnvironment, WebViewController,
        BrowserCheck, BrowserSettings, InitialNavigation, Ready, BrowserProcess
    }

    internal sealed class StartupDiagnosticContext
    {
        internal StartupStage Stage = StartupStage.RuntimePreparation;
        internal bool ProfileWritable;
        internal int? BackendExitCode;
        internal CoreWebView2WebErrorStatus? NavigationError;
        internal CoreWebView2ProcessFailedKind? ProcessFailure;
        internal string DataRootKind;
        internal string DiagnosticsDirectory;
        internal string TemporaryDirectory;
        internal bool DataDirectoryUnavailable;
    }

    internal sealed class StartupDiagnosticResult
    {
        internal string Path;
        internal bool UsedTemporaryDirectory;
        internal string Text;
        internal string CopyText;
    }

    internal static class StartupDiagnostics
    {
        internal static string StageKey(StartupStage stage) => stage switch
        {
            StartupStage.DotNetRuntime => "dotnet-runtime-check",
            StartupStage.RuntimeManifest => "runtime-manifest-check",
            StartupStage.RuntimePermissions => "runtime-permissions",
            StartupStage.ProfileDirectory => "profile-directory",
            StartupStage.SessionDirectory => "session-directory",
            StartupStage.BackendStart => "backend-start",
            StartupStage.BackendHandshake => "backend-handshake",
            StartupStage.WebViewEnvironment => "webview-environment",
            StartupStage.WebViewController => "webview-controller",
            StartupStage.BrowserCheck => "browser-check",
            StartupStage.BrowserSettings => "browser-settings",
            StartupStage.InitialNavigation => "initial-navigation",
            StartupStage.Ready => "ready",
            StartupStage.BrowserProcess => "browser-process",
            _ => "runtime-preparation"
        };

        private static string StageLabel(StartupStage stage) => stage switch
        {
            StartupStage.ProfileDirectory => "准备软件用户目录",
            StartupStage.SessionDirectory => "准备本机会话目录",
            StartupStage.BackendStart => "启动文档处理组件",
            StartupStage.BackendHandshake => "连接文档处理组件",
            StartupStage.WebViewEnvironment => "创建内嵌显示环境",
            StartupStage.WebViewController => "创建编辑窗口",
            StartupStage.BrowserCheck => "核验显示组件",
            StartupStage.BrowserSettings => "配置编辑窗口",
            StartupStage.InitialNavigation => "载入编辑页面",
            StartupStage.BrowserProcess => "编辑窗口运行",
            StartupStage.RuntimePermissions => "准备显示组件读取权限",
            StartupStage.DotNetRuntime => "核验软件运行组件",
            StartupStage.RuntimeManifest => "核验显示组件文件",
            _ => "准备软件运行组件"
        };

        internal static Dictionary<string, object> Create(StartupDiagnosticContext context, Exception exception)
        {
            // Explicit allowlist: never serialize exceptions, paths, URLs, environment or
            // the application's general state. Exception.Message can contain all of these.
            var components = new Dictionary<string, object>();
            foreach (var relative in new[] { "JijiEditor.exe", "coreclr.dll", "hostfxr.dll", "hostpolicy.dll",
                "System.Private.CoreLib.dll", "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll",
                "WebView2Loader.dll", "runtimes/win-x64/native/WebView2Loader.dll",
                "webview2/msedgewebview2.exe", "webview2/msedge.dll", "backend/jiji-engine.exe", "webview2-runtime.json" })
            {
                var path = System.IO.Path.Combine(AppDomain.CurrentDomain.BaseDirectory, relative.Replace('/', System.IO.Path.DirectorySeparatorChar));
                var component = new Dictionary<string, object> { ["exists"] = File.Exists(path) };
                try
                {
                    if (File.Exists(path) && !relative.EndsWith(".json", StringComparison.Ordinal))
                    {
                        var version = FileVersionInfo.GetVersionInfo(path);
                        component["fileVersion"] = NumericVersion(version.FileVersion);
                        component["productVersion"] = NumericVersion(version.ProductVersion);
                    }
                }
                catch (Exception failure) { component["inspectionError"] = Error(failure); }
                components[relative] = component;
            }
            var chain = new List<Dictionary<string, object>>();
            for (var current = exception; current != null && chain.Count < 8; current = current.InnerException)
                chain.Add(Error(current));
            return new Dictionary<string, object>
            {
                ["schemaVersion"] = 1,
                ["createdUtc"] = DateTime.UtcNow.ToString("O"),
                ["applicationVersion"] = Assembly.GetExecutingAssembly().GetName().Version?.ToString(),
                ["dotnetVersion"] = Environment.Version.ToString(),
                ["operatingSystem"] = ReadOperatingSystem(),
                ["osArchitecture"] = RuntimeInformation.OSArchitecture.ToString(),
                ["processArchitecture"] = RuntimeInformation.ProcessArchitecture.ToString(),
                ["stage"] = StageKey(context.Stage),
                ["profileWritable"] = context.ProfileWritable,
                ["dataRootKind"] = context.DataRootKind,
                ["dataDirectoryUnavailable"] = context.DataDirectoryUnavailable,
                ["backendExitCode"] = context.BackendExitCode,
                ["navigationError"] = context.NavigationError?.ToString(),
                ["processFailureKind"] = context.ProcessFailure?.ToString(),
                ["runtimeFailure"] = exception is BundledRuntimeException bundled ? bundled.Reason.ToString() : null,
                ["exceptions"] = chain,
                ["components"] = components
            };
        }

        internal static StartupDiagnosticResult Write(StartupDiagnosticContext context, Exception exception,
            string preferredDirectory = null, string fallbackDirectory = null)
        {
            var data = Create(context, exception);
            data["storage"] = "unavailable";
            var selectedDirectory = preferredDirectory == null && context.DiagnosticsDirectory != null;
            preferredDirectory ??= context.DataDirectoryUnavailable ? null : context.DiagnosticsDirectory ?? DefaultDirectory(false);
            fallbackDirectory ??= context.DataDirectoryUnavailable ? null : context.TemporaryDirectory == null ?
                DefaultDirectory(true) : System.IO.Path.Combine(context.TemporaryDirectory, "diagnostics");
            string saved = null;
            var fallback = false;
            var name = "startup-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N") + ".json";
            foreach (var directory in new[] { preferredDirectory, fallbackDirectory })
            {
                if (string.IsNullOrWhiteSpace(directory)) { fallback = true; continue; }
                try
                {
                    Directory.CreateDirectory(directory);
                    data["storage"] = fallback ? "temporary" : selectedDirectory ? "application-data" : "local-app-data";
                    var path = System.IO.Path.Combine(directory, name);
                    File.WriteAllText(path, JsonSerializer.Serialize(data, new JsonSerializerOptions { WriteIndented = true }), new UTF8Encoding(false));
                    saved = path;
                    break;
                }
                catch { fallback = true; }
            }
            var code = exception == null ? context.NavigationError?.ToString() ?? context.ProcessFailure?.ToString() ?? "未提供" : "0x" + exception.HResult.ToString("X8");
            if (exception is Win32Exception windows) code += " / Windows " + windows.NativeErrorCode;
            var innerDepth = 0;
            for (var inner = exception?.InnerException; inner != null && innerDepth++ < 7; inner = inner.InnerException)
            {
                code += " → 0x" + inner.HResult.ToString("X8");
                if (inner is Win32Exception native) code += " / Windows " + native.NativeErrorCode;
            }
            var operatingSystem = (Dictionary<string, object>)data["operatingSystem"];
            var text = "启动停在：" + StageLabel(context.Stage) + "（" + StageKey(context.Stage) + "）\r\n错误码：" + code +
                "\r\n软件版本：" + data["applicationVersion"] + "；Windows：" + operatingSystem["major"] + "." + operatingSystem["minor"] + "." + operatingSystem["build"] + "." + operatingSystem["revision"] +
                "\r\n\r\n" + (saved == null ? "诊断报告未能写入磁盘，请复制此窗口的信息。" : "诊断报告：\r\n" + saved) +
                "\r\n\r\n请提供阶段、错误码和诊断报告，以便确认具体原因。报告仅包含系统、组件版本和错误代码，不包含文档内容或会话凭据。";
            if (context.Stage == StartupStage.ProfileDirectory)
                text += context.DataDirectoryUnavailable ?
                    "\r\n未能选定可用的软件数据文件夹。再次打开软件时，可以选择当前账户能读写的其他本机文件夹。" :
                    "\r\n当前无法准备软件用户目录，请检查所选位置的读写权限和可用空间。";
            if (exception is BundledRuntimeException bundled)
            {
                var advice = bundled.Reason switch
                {
                    BundledRuntimeFailure.NetworkLocation => "请将完整软件文件夹复制到电脑本地磁盘后运行，不能直接从网络共享目录启动。",
                    BundledRuntimeFailure.IncompletePackage => "运行组件缺失或不完整。请重新下载并完整解压软件包，保留所有文件以及 webview2、backend 文件夹；无需另装运行组件。",
                    BundledRuntimeFailure.ManifestUnreadable => "显示组件清单无法读取。请完整重新解压安装包，并确认解压文件夹可读取。",
                    BundledRuntimeFailure.RuntimeMismatch => "实际加载的显示组件与随包版本不一致。请重新下载并完整解压最新版软件包。",
                    BundledRuntimeFailure.RuntimePermissions => "显示组件权限未能准备完成。请把完整软件包解压到当前账户可修改的本机“下载”或“桌面”文件夹后运行。",
                    _ => null
                };
                if (advice != null) text += "\r\n\r\n" + advice;
            }
            if (saved == null) data["storage"] = "unavailable";
            var copyText = text + "\r\n\r\n诊断详情：\r\n" + JsonSerializer.Serialize(data, new JsonSerializerOptions { WriteIndented = true });
            return new StartupDiagnosticResult { Path = saved, UsedTemporaryDirectory = fallback, Text = text, CopyText = copyText };
        }

        private static string DefaultDirectory(bool temporary)
        {
            try
            {
                var root = temporary ? System.IO.Path.GetTempPath() : Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                return string.IsNullOrWhiteSpace(root) ? null : System.IO.Path.Combine(root, "JijiEditor", "diagnostics");
            }
            catch { return null; }
        }

        private static Dictionary<string, object> Error(Exception exception)
        {
            var result = new Dictionary<string, object>
            {
                ["type"] = exception.GetType().FullName,
                ["hResult"] = "0x" + exception.HResult.ToString("X8")
            };
            if (exception is Win32Exception windows) result["nativeErrorCode"] = windows.NativeErrorCode;
            return result;
        }

        private static string NumericVersion(string value) => Version.TryParse(value, out var version) ? version.ToString() : null;

        private static Dictionary<string, object> ReadOperatingSystem()
        {
            var version = new OsVersion { Size = (uint)Marshal.SizeOf<OsVersion>(), ServicePack = "" };
            var source = "RtlGetVersion";
            try { if (RtlGetVersion(ref version) != 0) throw new InvalidOperationException(); }
            catch
            {
                var fallback = Environment.OSVersion.Version;
                version.Major = (uint)fallback.Major;
                version.Minor = (uint)fallback.Minor;
                version.Build = (uint)fallback.Build;
                source = "Environment.OSVersion";
            }
            int? updateBuildRevision = null;
            try
            {
                using var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows NT\CurrentVersion");
                if (key?.GetValue("UBR") is int revision) updateBuildRevision = revision;
            }
            catch { }
            return new Dictionary<string, object>
            {
                ["major"] = version.Major, ["minor"] = version.Minor,
                ["build"] = version.Build, ["revision"] = updateBuildRevision, ["source"] = source
            };
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct OsVersion
        {
            public uint Size, Major, Minor, Build, Platform;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string ServicePack;
        }
        [DllImport("ntdll.dll", CharSet = CharSet.Unicode)]
        private static extern int RtlGetVersion(ref OsVersion version);

        internal static void Show(IWin32Window owner, StartupDiagnosticResult result)
        {
            using var dialog = new Form { Text = "吉吉编辑软件 · 启动诊断", StartPosition = FormStartPosition.CenterParent,
                ClientSize = new Size(760, 400), MinimizeBox = false, MaximizeBox = false, AutoScaleMode = AutoScaleMode.Dpi };
            var details = new TextBox { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true,
                ScrollBars = ScrollBars.Vertical, Text = result.Text, Font = new Font("Microsoft YaHei UI", 10) };
            var actions = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 52, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
            var close = new Button { Text = "关闭", DialogResult = DialogResult.OK, AutoSize = true };
            var copy = new Button { Text = "复制诊断信息", AutoSize = true };
            copy.Click += (sender, e) =>
            {
                try { Clipboard.SetText(result.CopyText); copy.Text = "已复制"; }
                catch { details.Text = result.CopyText; details.SelectAll(); details.Focus(); }
            };
            actions.Controls.Add(close);
            actions.Controls.Add(copy);
            dialog.Controls.Add(details);
            dialog.Controls.Add(actions);
            dialog.AcceptButton = close;
            dialog.CancelButton = close;
            dialog.ShowDialog(owner);
        }
    }
}
