using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace JijiEditor
{
    /// <summary>Own the local engine and its descendants for exactly the GUI lifetime.</summary>
    internal sealed class EngineProcess : IDisposable
    {
        private readonly Process process;
        private readonly SafeFileHandle job;
        internal string TemporaryDirectory { get; private set; }

        private EngineProcess(Process process, SafeFileHandle job, string temporaryDirectory)
        {
            this.process = process;
            this.job = job;
            TemporaryDirectory = temporaryDirectory;
        }

        internal bool HasExited => process.HasExited;
        internal int? ExitCode => process.HasExited ? process.ExitCode : (int?)null;
        internal int WaitForExit() { process.WaitForExit(); return process.ExitCode; }

        internal static EngineProcess Start(string[] arguments, string temporaryDirectory = null)
        {
            var executable = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "backend", "jiji-engine.exe");
            if (!File.Exists(executable)) throw new FileNotFoundException("缺少编辑组件，请完整解压安装包后重试。");
            var job = CreateJobObject(IntPtr.Zero, null);
            if (job.IsInvalid) throw new Win32Exception();
            var information = new JobExtendedLimitInformation();
            information.BasicLimitInformation.LimitFlags = 0x00002000; // KILL_ON_JOB_CLOSE
            if (!SetInformationJobObject(job, 9, ref information, (uint)Marshal.SizeOf(information)))
            {
                job.Dispose();
                throw new Win32Exception();
            }
            Process process = null;
            try
            {
                var start = new ProcessStartInfo(executable)
                {
                    Arguments = JoinArguments(arguments),
                    WorkingDirectory = Path.GetDirectoryName(executable),
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };
                if (temporaryDirectory != null)
                    foreach (var variable in new[] { "TEMP", "TMP", "TMPDIR" })
                        start.Environment[variable] = temporaryDirectory;
                process = new Process { StartInfo = start };
                // The Python server prints its token-bearing URL; deliberately discard it.
                process.OutputDataReceived += (sender, e) => { };
                process.ErrorDataReceived += (sender, e) => { };
                if (!process.Start()) throw new InvalidOperationException("编辑组件无法启动。");
                if (!AssignProcessToJobObject(job, process.Handle)) throw new Win32Exception();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                return new EngineProcess(process, job, temporaryDirectory);
            }
            catch
            {
                if (process != null)
                {
                    try { if (!process.HasExited) process.Kill(); } catch { }
                    process.Dispose();
                }
                job.Dispose();
                throw;
            }
        }

        // Windows CommandLineToArgvW quoting, including trailing slashes and embedded quotes.
        private static string JoinArguments(string[] arguments)
        {
            var output = new StringBuilder();
            foreach (var argument in arguments)
            {
                if (output.Length != 0) output.Append(' ');
                output.Append('"');
                var slashes = 0;
                foreach (var character in argument)
                {
                    if (character == '\\') { slashes++; continue; }
                    if (character == '"') output.Append('\\', slashes * 2 + 1);
                    else output.Append('\\', slashes);
                    output.Append(character);
                    slashes = 0;
                }
                output.Append('\\', slashes * 2).Append('"');
            }
            return output.ToString();
        }

        public void Dispose()
        {
            // Closing the job terminates all descendants, including PyInstaller helpers.
            job.Dispose();
            try { process.WaitForExit(3000); } catch { }
            process.Dispose();
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JobBasicLimitInformation
        {
            public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass, SchedulingClass;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct IoCounters
        {
            public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
            public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct JobExtendedLimitInformation
        {
            public JobBasicLimitInformation BasicLimitInformation;
            public IoCounters IoInfo;
            public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateJobObject(IntPtr security, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool SetInformationJobObject(SafeFileHandle job, int informationClass,
            ref JobExtendedLimitInformation information, uint length);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool AssignProcessToJobObject(SafeFileHandle job, IntPtr process);
    }
}
