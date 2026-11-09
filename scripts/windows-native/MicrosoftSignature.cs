using System;
using System.Runtime.InteropServices;
using System.Security.Cryptography.X509Certificates;

namespace JijiEditor
{
    internal static class MicrosoftSignature
    {
        internal static bool IsTrusted(string path)
        {
            var file = new WinTrustFileInfo { Size = (uint)Marshal.SizeOf(typeof(WinTrustFileInfo)), Path = path };
            var pointer = Marshal.AllocHGlobal(Marshal.SizeOf(file));
            try
            {
                Marshal.StructureToPtr(file, pointer, false);
                var trust = new WinTrustData
                {
                    Size = (uint)Marshal.SizeOf(typeof(WinTrustData)), UiChoice = 2,
                    UnionChoice = 1, FileInfo = pointer, StateAction = 0,
                    ProviderFlags = 0x00001000 // Verify signature and trust using the local certificate cache.
                };
                var action = new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");
                if (WinVerifyTrust(new IntPtr(-1), ref action, ref trust) != 0) return false;
                using (var certificate = new X509Certificate2(X509Certificate.CreateFromSignedFile(path)))
                    return certificate.GetNameInfo(X509NameType.SimpleName, false) == "Microsoft Corporation";
            }
            catch { return false; }
            finally
            {
                Marshal.DestroyStructure(pointer, typeof(WinTrustFileInfo));
                Marshal.FreeHGlobal(pointer);
            }
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct WinTrustFileInfo
        {
            public uint Size;
            [MarshalAs(UnmanagedType.LPWStr)] public string Path;
            public IntPtr File, KnownSubject;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct WinTrustData
        {
            public uint Size;
            public IntPtr PolicyCallbackData, SipClientData;
            public uint UiChoice, RevocationChecks, UnionChoice;
            public IntPtr FileInfo;
            public uint StateAction;
            public IntPtr StateData, UrlReference;
            public uint ProviderFlags, UiContext;
            public IntPtr SignatureSettings;
        }
        [DllImport("wintrust.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
        private static extern int WinVerifyTrust(IntPtr window, ref Guid action, ref WinTrustData data);
    }
}
