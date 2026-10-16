# 파이썬 공부 | scripts/build_exe.py
# Windows 컴파일러를 사용해 Jarvis 실행 파일을 만듭니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Compile native Windows GUI executable Jarvis.exe using standard csc.exe."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# CSHARP_SOURCE에 문자열을 대입합니다.
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
                if (!File.Exists(Path.Combine(baseDir, "pyproject.toml")))
                {
                    baseDir = Directory.GetParent(baseDir.TrimEnd(Path.DirectorySeparatorChar)).FullName;
                }
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


# find_csc(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: Path | None.
def find_csc() -> Path | None:
    # candidates에 리스트(순서가 있고 수정 가능)을 대입합니다.
    candidates = [
        Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
        Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"),
    ]
    # for 반복문: 대상의 항목을 하나씩 csc에 대입하며 아래 블록을 실행합니다.
    for csc in candidates:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: csc.is_file().
        if csc.is_file():
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return csc
    # None을 반환하고 이 함수의 실행을 끝냅니다.
    return None


# build_launcher(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: output_exe.
# 반환 타입 힌트: 정수(int).
def build_launcher(output_exe: Path | None = None) -> int:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: output_exe is None.
    if output_exe is None:
        # 오른쪽 식을 계산한 값을 output_exe에 대입합니다.
        output_exe = REPOSITORY_ROOT / "bin" / "Jarvis.exe"
    output_exe.parent.mkdir(parents=True, exist_ok=True)

    # find_csc()의 반환값을 csc에 대입합니다.
    csc = find_csc()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: csc is None.
    if csc is None:
        # 값을 텍스트로 출력합니다.
        print("[ERROR] Windows csc.exe compiler not found.", file=sys.stderr)
        # 1을 반환하고 이 함수의 실행을 끝냅니다.
        return 1

    # 값을 텍스트로 출력합니다.
    print(f"[*] Compiling native Jarvis.exe using {csc}...")
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with tempfile.TemporaryDirectory() as tmp_dir:
        # 오른쪽 식을 계산한 값을 src_file에 대입합니다.
        src_file = Path(tmp_dir) / "Launcher.cs"
        # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
        src_file.write_text(CSHARP_SOURCE, encoding="utf-8")

        # cmd에 리스트(순서가 있고 수정 가능)을 대입합니다.
        cmd = [
            str(csc),
            "/nologo",
            "/target:winexe",
            "/optimize+",
            "/platform:anycpu",
            f"/out:{output_exe}",
            str(src_file),
        ]

        # subprocess.run()의 반환값을 result에 대입합니다.
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: result.returncode != 0.
        if result.returncode != 0:
            # 값을 텍스트로 출력합니다.
            print(f"[ERROR] Compilation failed:\n{result.stderr}\n{result.stdout}", file=sys.stderr)
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return result.returncode

    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: output_exe.is_file().
    if output_exe.is_file():
        # 오른쪽 식을 계산한 값을 size_kb에 대입합니다.
        size_kb = output_exe.stat().st_size / 1024
        # 값을 텍스트로 출력합니다.
        print(f"[SUCCESS] Native executable created: {output_exe} ({size_kb:.1f} KB)")
        # 0을 반환하고 이 함수의 실행을 끝냅니다.
        return 0
    # 앞선 조건이 거짓이면 이 블록을 실행합니다.
    else:
        # 값을 텍스트로 출력합니다.
        print("[ERROR] Output file not found after compilation.", file=sys.stderr)
        # 1을 반환하고 이 함수의 실행을 끝냅니다.
        return 1


# 이 파일을 실행 진입점으로 사용할 때만 아래 코드를 실행합니다. import할 때는 실행하지 않습니다.
if __name__ == "__main__":
    # sys.exit()을 호출해 작업을 수행합니다.
    sys.exit(build_launcher())
