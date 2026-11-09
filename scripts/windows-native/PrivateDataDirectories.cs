using System;
using System.Collections.Generic;
using System.IO;
using System.Security;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Windows.Forms;

namespace JijiEditor
{
    /// <summary>Keep all mutable application data in one verified, account-private local root.</summary>
    internal sealed class PrivateDataDirectories
    {
        internal string Root { get; private set; }
        internal string Profile { get; private set; }
        internal string Temp { get; private set; }
        internal string Diagnostics { get; private set; }
        internal string Session { get; private set; }
        internal string Kind { get; private set; }

        internal static PrivateDataDirectories Select(IWin32Window owner, string fixedVersion, bool verification)
        {
            if (!Version.TryParse(fixedVersion, out _)) throw new InvalidDataException();
            using var identity = WindowsIdentity.GetCurrent();
            var user = identity.User ?? throw new UnauthorizedAccessException();
            // A portable copy may be used by multiple Windows accounts. Never share profiles.
            var suffix = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(user.Value))).Substring(0, 20);
            var folderName = "JijiData-" + suffix;
            var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            var primary = string.IsNullOrWhiteSpace(local) ? null : Path.Combine(local, "JijiEditor");
            var fallback = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, folderName);
            if (verification)
            {
                primary = Environment.GetEnvironmentVariable("JIJI_VERIFY_DATA_ROOT") ?? primary;
                fallback = Environment.GetEnvironmentVariable("JIJI_VERIFY_FALLBACK_ROOT") ?? fallback;
            }
            Exception lastFailure = null;
            foreach (var candidate in new[] { (Path: primary, Kind: "local-app-data"),
                                               (Path: fallback, Kind: "application-directory") })
            {
                var selected = TryPrepare(candidate.Path, candidate.Kind, fixedVersion, user, out lastFailure);
                if (selected != null) return selected;
            }
            // Automated verification must report a failure instead of waiting for an unseen dialog.
            if (verification) throw new PrivateDataDirectoryException(lastFailure);
            using var picker = new FolderBrowserDialog
            {
                Description = "软件暂时无法使用默认保存位置，请选择一个本机文件夹，用于存放吉吉的设置和临时文件。",
                UseDescriptionForTitle = true,
                ShowNewFolderButton = true
            };
            while (picker.ShowDialog(owner) == DialogResult.OK)
            {
                var selected = TryPrepare(Path.Combine(picker.SelectedPath, folderName), "user-selected",
                    fixedVersion, user, out lastFailure);
                if (selected != null) return selected;
                if (MessageBox.Show(owner,
                    "这个位置无法安全保存软件数据。请选择当前账户可以读写的本机文件夹。\n\n所选文件夹本身的权限不会被更改。",
                    "吉吉编辑软件", MessageBoxButtons.RetryCancel, MessageBoxIcon.Information) != DialogResult.Retry)
                    break;
            }
            throw new PrivateDataDirectoryException(lastFailure);
        }

        private static PrivateDataDirectories TryPrepare(string path, string kind, string fixedVersion,
            SecurityIdentifier user, out Exception failure)
        {
            string session = null;
            try
            {
                var root = ValidateLocalPath(path);
                EnsurePrivateDirectory(root, user);
                ProbeWritable(root);
                var web = Path.Combine(root, "WebView2");
                EnsurePrivateDirectory(web, user);
                // Fixed runtime versions never share or downgrade another version's profile.
                var profile = Path.Combine(web, "Fixed-" + fixedVersion);
                EnsurePrivateDirectory(profile, user);
                ProbeWritable(profile);
                var temp = Path.Combine(root, "Temp");
                EnsurePrivateDirectory(temp, user);
                ProbeWritable(temp);
                var diagnostics = Path.Combine(root, "diagnostics");
                EnsurePrivateDirectory(diagnostics, user);
                ProbeWritable(diagnostics);
                var sessions = Path.Combine(root, "Sessions");
                EnsurePrivateDirectory(sessions, user);
                session = Path.Combine(sessions, "session-" + Guid.NewGuid().ToString("N"));
                EnsurePrivateDirectory(session, user);
                ProbeWritable(session);
                failure = null;
                return new PrivateDataDirectories
                {
                    Root = root, Profile = profile, Temp = temp, Diagnostics = diagnostics,
                    Session = session, Kind = kind
                };
            }
            catch (Exception exception) when (exception is UnauthorizedAccessException || exception is IOException ||
                exception is SecurityException || exception is ArgumentException || exception is NotSupportedException)
            {
                if (session != null)
                    try { Directory.Delete(session, false); } catch { }
                failure = exception;
                return null;
            }
        }

        private static string ValidateLocalPath(string path)
        {
            if (string.IsNullOrWhiteSpace(path) || !Path.IsPathFullyQualified(path))
                throw new IOException("A local absolute data directory is required.");
            var full = Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
            var driveRoot = Path.GetPathRoot(full);
            if (full.StartsWith(@"\\", StringComparison.Ordinal) || new Uri(full).IsUnc ||
                string.Equals(full, driveRoot, StringComparison.OrdinalIgnoreCase))
                throw new IOException("The data directory must be a local application folder.");
            var drive = new DriveInfo(driveRoot);
            if (drive.DriveType != DriveType.Fixed && drive.DriveType != DriveType.Removable)
                throw new IOException("The data directory must be on a local disk.");
            // Resolve no junctions, symlinks, cloud placeholders or network redirects in the chain.
            for (var current = new DirectoryInfo(full); current != null; current = current.Parent)
            {
                try
                {
                    var attributes = File.GetAttributes(current.FullName);
                    if ((attributes & FileAttributes.ReparsePoint) != 0 || (attributes & FileAttributes.Directory) == 0)
                        throw new IOException("The data directory contains a redirected or non-directory component.");
                }
                catch (FileNotFoundException) { }
                catch (DirectoryNotFoundException) { }
            }
            return full;
        }

        private static void EnsurePrivateDirectory(string path, SecurityIdentifier user)
        {
            ValidateLocalPath(path);
            var directory = new DirectoryInfo(path);
            if (!directory.Exists)
            {
                if (directory.Parent == null || !directory.Parent.Exists) throw new DirectoryNotFoundException();
                var security = new DirectorySecurity();
                security.SetOwner(user);
                security.SetAccessRuleProtection(true, false);
                foreach (var principal in new[] { user, new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null) })
                    security.AddAccessRule(new FileSystemAccessRule(principal, FileSystemRights.FullControl,
                        InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                        PropagationFlags.None, AccessControlType.Allow));
                // Supply the DACL at creation: never temporarily expose document/session data.
                directory.Create(security);
            }
            ValidateLocalPath(path);
            var acl = directory.GetAccessControl(AccessControlSections.Access | AccessControlSections.Owner);
            var descriptor = new RawSecurityDescriptor(acl.GetSecurityDescriptorBinaryForm(), 0);
            if (descriptor.DiscretionaryAcl == null) throw new UnauthorizedAccessException();
            if (!IsTrusted(acl.GetOwner(typeof(SecurityIdentifier)), user)) throw new UnauthorizedAccessException();
            foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier)))
                if (rule.AccessControlType == AccessControlType.Allow && !IsTrusted(rule.IdentityReference, user))
                    throw new UnauthorizedAccessException("The application directory is accessible by other accounts.");
            // Existing ACLs, including explicit deny rules, are never rewritten.
        }

        private static bool IsTrusted(IdentityReference identity, SecurityIdentifier user) =>
            identity.Equals(user) || identity.Equals(new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null)) ||
            identity.Equals(new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null));

        private static void ProbeWritable(string directory)
        {
            BundledRuntime.EnsureProfileWritable(directory);
            var child = Path.Combine(directory, ".jiji-directory-check-" + Guid.NewGuid().ToString("N"));
            try { Directory.CreateDirectory(child); Directory.Delete(child); }
            finally { try { if (Directory.Exists(child)) Directory.Delete(child); } catch { } }
        }

        internal void ApplyProcessTemp()
        {
            foreach (var variable in new[] { "TEMP", "TMP", "TMPDIR" })
                Environment.SetEnvironmentVariable(variable, Temp);
            if (!SamePath(Path.GetTempPath(), Temp)) throw new IOException("The process temporary directory was not applied.");
            ProbeWritable(Path.GetTempPath());
        }

        internal bool Contains(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) return false;
            var full = Path.GetFullPath(path);
            return full.StartsWith(Root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
        }

        internal void Report(IDictionary<string, object> report, string backendTemp)
        {
            report["dataRootKind"] = Kind;
            report["dataRootFallback"] = Kind != "local-app-data";
            report["privateDataRoot"] = true;
            report["profileUnderDataRoot"] = Contains(Profile);
            report["sessionUnderDataRoot"] = Contains(Session);
            report["processTempUnderDataRoot"] = Contains(Path.GetTempPath()) && SamePath(Path.GetTempPath(), Temp);
            report["backendTempUnderDataRoot"] = Contains(backendTemp) && SamePath(backendTemp, Temp);
            report["tempRootWritable"] = true;
            report["diagnosticsRootWritable"] = true;
            report["profileDataRelative"] = Path.GetRelativePath(Root, Profile);
            report["sessionDataRelative"] = Path.GetRelativePath(Root, Session);
            report["backendTempRelative"] = Path.GetRelativePath(Root, backendTemp);
        }

        private static bool SamePath(string left, string right) => string.Equals(
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(left)),
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(right)), StringComparison.OrdinalIgnoreCase);
    }

    internal sealed class PrivateDataDirectoryException : IOException
    {
        internal PrivateDataDirectoryException(Exception inner) : base("No private writable application data directory was selected.", inner) { }
    }
}
