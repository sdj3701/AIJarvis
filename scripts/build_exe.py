"""Compile native Windows GUI executable Jarvis.exe using standard csc.exe."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

CSHARP_SOURCE = r"""using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

namespace JarvisLauncher
{
    static class Program
    {
        [STAThread]
        static int Main(string[] args)
        {
            try
            {
                string baseDir = AppDomain.CurrentDomain.BaseDirectory;
                string pythonw = Path.Combine(baseDir, ".venv", "Scripts", "pythonw.exe");
                
                if (!File.Exists(pythonw))
                {
                    pythonw = Path.Combine(baseDir, ".venv", "Scripts", "python.exe");
                }

                if (!File.Exists(pythonw))
                {
                    MessageBox.Show(
                        "자비스 가상환경(.venv)을 찾을 수 없습니다.\n\n" +
                        "확인한 경로: " + pythonw + "\n\n" +
                        "프로젝트 루트에서 'python scripts\\bootstrap.py'를 먼저 실행해 주세요.",
                        "JARVIS Launcher — 환경 오류",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error
                    );
                    return 1;
                }

                string cliArgs = "-m app --gui";
                if (args != null && args.Length > 0)
                {
                    cliArgs = string.Join(" ", args);
                }

                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = pythonw;
                psi.Arguments = cliArgs;
                psi.WorkingDirectory = baseDir;
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.WindowStyle = ProcessWindowStyle.Hidden;

                Process proc = Process.Start(psi);
                if (proc == null)
                {
                    MessageBox.Show(
                        "자비스 프로세스를 시작하지 못했습니다.",
                        "JARVIS Error",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error
                    );
                    return 2;
                }
                return 0;
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    "자비스 실행 중 예기치 않은 오류가 발생했습니다:\n\n" + ex.Message,
                    "JARVIS Fatal Error",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return 99;
            }
        }
    }
}
"""


def find_csc() -> Path | None:
    candidates = [
        Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
        Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"),
    ]
    for csc in candidates:
        if csc.is_file():
            return csc
    return None


def build_launcher(output_exe: Path | None = None) -> int:
    if output_exe is None:
        output_exe = REPOSITORY_ROOT / "Jarvis.exe"

    csc = find_csc()
    if csc is None:
        print("[ERROR] Windows csc.exe compiler not found.", file=sys.stderr)
        return 1

    print(f"[*] Compiling native Jarvis.exe using {csc}...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        src_file = Path(tmp_dir) / "Launcher.cs"
        src_file.write_text(CSHARP_SOURCE, encoding="utf-8")

        cmd = [
            str(csc),
            "/nologo",
            "/target:winexe",
            "/optimize+",
            "/platform:anycpu",
            f"/out:{output_exe}",
            str(src_file),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(f"[ERROR] Compilation failed:\n{result.stderr}\n{result.stdout}", file=sys.stderr)
            return result.returncode

    if output_exe.is_file():
        size_kb = output_exe.stat().st_size / 1024
        print(f"[SUCCESS] Native executable created: {output_exe} ({size_kb:.1f} KB)")
        return 0
    else:
        print("[ERROR] Output file not found after compilation.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(build_launcher())
