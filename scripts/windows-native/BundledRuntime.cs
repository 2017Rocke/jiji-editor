using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.Json;

namespace JijiEditor
{
    /// <summary>Use only the application-local runtimes, including on a clean offline PC.</summary>
    internal static class BundledRuntime
    {
        internal static string Prepare(string profileRoot, out string profile, IDictionary<string, object> report)
        {
            var application = Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory);
            if (new Uri(application).IsUnc || new DriveInfo(Path.GetPathRoot(application)).DriveType == DriveType.Network)
                throw new BundledRuntimeException("请把完整的吉吉软件文件夹复制到电脑本地磁盘后再打开，不能直接从网络共享目录运行。");

            foreach (var file in new[] { "coreclr.dll", "hostfxr.dll", "System.Private.CoreLib.dll", "System.Windows.Forms.dll" })
                if (!File.Exists(Path.Combine(application, file))) throw IncompletePackage();
            string clrModule = null;
            using (var process = Process.GetCurrentProcess())
                foreach (ProcessModule module in process.Modules)
                    if (string.Equals(module.ModuleName, "coreclr.dll", StringComparison.OrdinalIgnoreCase))
                        clrModule = module.FileName;
            var runtimeDirectory = RuntimeEnvironment.GetRuntimeDirectory();
            var localClr = IsWithin(application, runtimeDirectory) && IsWithin(application, clrModule);
            report["selfContainedDotNet"] = localClr;
            if (!localClr) throw IncompletePackage();
            report["dotnetRuntimeVersion"] = Environment.Version.ToString();
            report["dotnetRuntimeDirectory"] = Path.GetRelativePath(application, runtimeDirectory);
            report["dotnetRuntimeModule"] = Path.GetRelativePath(application, clrModule);

            var runtime = Path.Combine(application, "webview2");
            var executable = Path.Combine(runtime, "msedgewebview2.exe");
            var manifest = Path.Combine(application, "webview2-runtime.json");
            if (!File.Exists(executable) || !File.Exists(manifest)) throw IncompletePackage();
            var fixedVersion = FileVersionInfo.GetVersionInfo(executable).ProductVersion;
            try
            {
                using var metadata = JsonDocument.Parse(File.ReadAllText(manifest));
                if (metadata.RootElement.GetProperty("architecture").GetString() != "x64" ||
                    metadata.RootElement.GetProperty("version").GetString() != fixedVersion)
                    throw IncompletePackage();
            }
            catch (Exception exception) when (exception is JsonException || exception is KeyNotFoundException ||
                                               exception is InvalidOperationException || exception is IOException)
            { throw IncompletePackage(); }
            if (string.IsNullOrWhiteSpace(fixedVersion)) throw IncompletePackage();
            report["bundledWebView2ExpectedVersion"] = fixedVersion;
            EnsureAppContainerReadAccess(runtime);
            // Different fixed versions must not downgrade or share an Evergreen profile.
            profile = Path.Combine(profileRoot, "Fixed-" + fixedVersion);

            // Explicit options alone can be overridden by inherited WEBVIEW2_* variables.
            // Remove those overrides and set our own fixed executable/profile locations.
            foreach (DictionaryEntry item in Environment.GetEnvironmentVariables())
            {
                var key = item.Key as string;
                if (key != null && key.StartsWith("WEBVIEW2_", StringComparison.OrdinalIgnoreCase))
                    Environment.SetEnvironmentVariable(key, null);
            }
            Environment.SetEnvironmentVariable("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER", runtime);
            Environment.SetEnvironmentVariable("WEBVIEW2_USER_DATA_FOLDER", profile);
            Environment.SetEnvironmentVariable("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--disable-component-update");
            return runtime;
        }

        internal static void VerifyBrowser(uint processId, string version, IDictionary<string, object> report)
        {
            var application = Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory);
            var expected = Path.Combine(application, "webview2", "msedgewebview2.exe");
            string actual;
            using (var browser = Process.GetProcessById(checked((int)processId))) actual = browser.MainModule.FileName;
            var matches = string.Equals(Path.GetFullPath(actual), expected, StringComparison.OrdinalIgnoreCase) &&
                string.Equals(version, (string)report["bundledWebView2ExpectedVersion"], StringComparison.Ordinal);
            report["bundledWebView2"] = matches;
            if (!matches) throw new BundledRuntimeException("吉吉未能加载软件包内的显示组件。请重新下载并完整解压最新版安装包后再打开。");
            report["webView2RuntimeVersion"] = version;
            report["webView2Executable"] = Path.GetRelativePath(application, actual);
        }

        private static void EnsureAppContainerReadAccess(string runtime)
        {
            // Fixed WebView2 >= 120 needs these two inheritable RX grants on Windows 10.
            // The user owns an extracted portable folder, so this requires no elevation.
            // Never grant write access or weaken the WebView2 sandbox.
            try
            {
                var directory = new DirectoryInfo(runtime);
                var acl = directory.GetAccessControl(AccessControlSections.Access);
                var changed = false;
                foreach (var value in new[] { "S-1-15-2-1", "S-1-15-2-2" })
                {
                    var identity = new SecurityIdentifier(value);
                    var found = false;
                    foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier)))
                        if (rule.IdentityReference.Equals(identity) && rule.AccessControlType == AccessControlType.Allow &&
                            (rule.FileSystemRights & FileSystemRights.ReadAndExecute) == FileSystemRights.ReadAndExecute &&
                            (rule.InheritanceFlags & (InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit)) ==
                            (InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit)) found = true;
                    if (found) continue;
                    acl.AddAccessRule(new FileSystemAccessRule(identity, FileSystemRights.ReadAndExecute,
                        InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                        PropagationFlags.None, AccessControlType.Allow));
                    changed = true;
                }
                if (changed) directory.SetAccessControl(acl);
            }
            catch (Exception exception) when (exception is UnauthorizedAccessException || exception is IOException ||
                                               exception is System.Security.SecurityException)
            {
                throw new BundledRuntimeException("无法准备软件包内的显示组件。请把整个安装包重新解压到本机“下载”或“桌面”等你可以修改的文件夹后打开。无需安装其他运行组件。");
            }
        }

        private static bool IsWithin(string directory, string path)
        {
            if (string.IsNullOrWhiteSpace(path)) return false;
            var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(directory));
            var actual = Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
            return string.Equals(root, actual, StringComparison.OrdinalIgnoreCase) ||
                actual.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
        }

        private static BundledRuntimeException IncompletePackage() => new BundledRuntimeException(
            "软件包内的运行组件不完整。请重新下载最新版安装包并完整解压，保留所有文件和 webview2、backend 文件夹，再打开 JijiEditor.exe。无需另外安装 .NET 或 WebView2。");
    }

    internal sealed class BundledRuntimeException : Exception
    {
        internal BundledRuntimeException(string message) : base(message) { }
    }
}
