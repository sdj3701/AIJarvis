"""Compile native Windows GUI executable Jarvis.exe using standard csc.exe."""

# [파일 역할] 파이썬 앱을 시작해 주는 작은 Windows 실행 파일(Jarvis.exe)을 만든다.
# 파이썬 코드 자체를 EXE에 모두 넣는 방식이 아니다. EXE는 프로젝트의 .venv 안에 있는
# pythonw.exe 또는 python.exe를 찾아 `-m app --gui`라는 인수로 실행한다.
# 실행 흐름: build_launcher() → C# 컴파일러 탐색 → 임시 .cs 파일 작성 → 컴파일.
# 직접 실행하면 프로젝트의 Jarvis.exe를 생성하거나 덮어쓸 수 있다.
# 이 스크립트는 argparse를 쓰지 않으므로 --help만 붙여도 빌드 함수가 실행된다.
# 학습 포인트: Python 문자열에 다른 언어 코드 담기, Path | None, 외부 프로세스 실행.
from __future__ import annotations

# subprocess: 컴파일러 실행 / sys: 오류 출력과 종료 / tempfile: 임시 작업 폴더.
# Path: 경로를 객체로 표현하고 파일 존재 여부, 크기 등을 확인한다.
import subprocess
import sys
import tempfile
from pathlib import Path

# 현재 파일 → scripts 폴더 → 프로젝트 폴더 순으로 부모 경로를 찾는다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# 아래 r"""..."""는 여러 줄짜리 raw 문자열이다. 내부는 파이썬이 실행하는 코드가
# 아니라 C# 컴파일러에게 넘길 텍스트다. r 덕분에 \n 같은 문자를 파이썬이 먼저
# 줄바꿈으로 바꾸지 않고 C# 소스에 그대로 전달할 수 있다.
#
# C# 코드 읽기 안내 (중괄호 {}가 파이썬의 들여쓰기와 비슷한 블록 역할을 한다):
# - using: C#에서 사용할 네임스페이스. Python의 import와 역할이 비슷하다.
# - namespace / class Program: 런처 코드를 묶는 이름 공간과 클래스.
# - [STAThread]: Main 스레드의 COM 아파트 모델을 STA로 지정하는 C# 특성이다.
# - Main(string[] args): EXE가 시작될 때 실행되는 진입점. args는 받은 인수 목록이다.
# - baseDir: 실행된 EXE가 있는 폴더. 그 아래 .venv/Scripts에서 파이썬을 찾는다.
# - pythonw.exe: 콘솔 창 없이 실행하는 파이썬. 없으면 python.exe를 시도한다.
# - MessageBox.Show: 오류를 Windows 대화상자로 알린다.
# - cliArgs: 기본은 '-m app --gui'. 인수가 있으면 공백으로 이어 붙인 문자열로 교체한다.
#   이 코드는 공백이 포함된 개별 인수를 별도로 인용하는 처리는 하지 않는다.
# - ProcessStartInfo: 실행 파일, 인수, 작업 폴더와 창 숨김 여부를 설정한다.
# - Process.Start: 앱 프로세스를 시작한다. 앱 종료를 기다리는 코드는 없다.
# - return 0/1/2/99: 런처 시작 결과의 종료 코드다. 앱의 최종 종료 코드는 아니다.
# - catch: Python의 except처럼 실행 중 예외를 처리한다.
# 아래 오류 문구는 bootstrap.py를 안내하지만, 그 스크립트는 데이터/DB 준비용이다.
# .venv를 생성하는 작업 자체는 이 C# 코드에도 bootstrap.py에도 포함되어 있지 않다.
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
    # -> Path | None은 '찾으면 경로, 못 찾으면 None'을 반환한다는 타입 힌트다.
    # r 접두사로 Windows 경로의 역슬래시를 이스케이프 문자로 해석하지 않게 한다.
    candidates = [
        Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
        Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"),
    ]
    for csc in candidates:
        # 목록 순서대로 확인하고 첫 번째 파일을 찾는 즉시 함수 실행을 끝낸다.
        if csc.is_file():
            return csc
    # PATH나 모든 .NET 설치 폴더를 검색하는 것은 아니고 위 두 후보만 확인한다.
    return None


def build_launcher(output_exe: Path | None = None) -> int:
    # 호출자가 출력 경로를 생략하면 기본 파일명을 사용한다.
    # None 비교에는 ==보다 is None을 쓴다. '값 없음'을 나타내는 단일 객체이기 때문이다.
    if output_exe is None:
        output_exe = REPOSITORY_ROOT / "Jarvis.exe"

    csc = find_csc()
    if csc is None:
        # stderr는 오류 출력 통로다. 1을 반환해 컴파일러가 없다는 실패를 알린다.
        print("[ERROR] Windows csc.exe compiler not found.", file=sys.stderr)
        return 1

    print(f"[*] Compiling native Jarvis.exe using {csc}...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        # with 블록이 끝나면 임시 폴더와 안의 소스 파일은 자동 정리된다.
        # 최종 EXE는 프로젝트 쪽에 쓰므로 이 임시 폴더의 정리 대상이 아니다.
        src_file = Path(tmp_dir) / "Launcher.cs"
        # 문자열 안에 담아 둔 C# 코드를 실제 .cs 파일로 저장한다. 한글 때문에 UTF-8 지정.
        src_file.write_text(CSHARP_SOURCE, encoding="utf-8")

        # 명령을 문자열 목록으로 만들면 실행 파일과 각 인수의 경계를 명확히 전달한다.
        # /nologo: 배너 생략 /target:winexe: GUI 실행 파일 /optimize+: 최적화.
        # /platform:anycpu: 특정 CPU 아키텍처로 제한하지 않음 /out: 결과 경로 지정.
        cmd = [
            str(csc),
            "/nologo",
            "/target:winexe",
            "/optimize+",
            "/platform:anycpu",
            f"/out:{output_exe}",
            str(src_file),
        ]

        # run은 컴파일러가 끝날 때까지 기다린다. 출력은 문자열로 result에 모은다.
        # check=False이므로 실패 종료 코드를 직접 확인한다. 실행 자체의 OS 오류는 별개다.
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(f"[ERROR] Compilation failed:\n{result.stderr}\n{result.stdout}", file=sys.stderr)
            return result.returncode

    if output_exe.is_file():
        # 컴파일러 성공 코드에 더해 출력 파일이 있는지도 확인하고 크기를 표시한다.
        # st_size는 바이트 단위, :.1f는 소수점 아래 한 자리로 표시하는 서식이다.
        size_kb = output_exe.stat().st_size / 1024
        print(f"[SUCCESS] Native executable created: {output_exe} ({size_kb:.1f} KB)")
        return 0
    else:
        print("[ERROR] Output file not found after compilation.", file=sys.stderr)
        return 1


# 직접 실행하면 빌드를 수행한다. import하면 함수와 문자열만 준비하고 빌드는 하지 않는다.
# sys.exit(정수)는 SystemExit를 발생시켜 그 정수를 프로그램 종료 코드로 전달한다.
if __name__ == "__main__":
    sys.exit(build_launcher())
