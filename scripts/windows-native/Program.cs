using System;
using System.IO;
using System.Windows.Forms;

namespace JijiEditor
{
    internal static class Program
    {
        [STAThread]
        private static int Main(string[] args)
        {
            // Keep the portable package verification interface independent of the GUI.
            // The job object also kills the engine if a verifier terminates this process.
            if (Array.IndexOf(args, "--no-browser") >= 0)
            {
                try
                {
                    using (var engine = EngineProcess.Start(args))
                        return engine.WaitForExit();
                }
                catch { return 1; }
            }

            string verificationDirectory = null;
            if (args.Length != 0)
            {
                if (args.Length != 2 || args[0] != "--verify-native") return 2;
                try
                {
                    verificationDirectory = Path.GetFullPath(args[1]);
                    Directory.CreateDirectory(verificationDirectory);
                }
                catch { return 2; }
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            using (var window = new EditorWindow(verificationDirectory))
            {
                Application.Run(window);
                return window.ExitCode;
            }
        }
    }
}
