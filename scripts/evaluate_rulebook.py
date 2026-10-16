# 파이썬 공부 | scripts/evaluate_rulebook.py
# 로컬 AI에 평가 질문을 보내 응답 규칙 준수 결과를 확인합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Opt-in, local-only 50-question rulebook format evaluation (no tools/TTS)."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from pathlib import Path

from app.orchestrator.response_presenter import one_sentence
from app.orchestrator.rulebook import load_rulebook

# QUESTIONS에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
QUESTIONS = (
    "대한민국의 수도는 어디야?", "삼각형의 변은 몇 개야?", "2 더하기 3은 얼마야?",
    "10에서 4를 빼면?", "7 곱하기 8은?", "100 나누기 4는?", "1시간은 몇 분이야?",
    "1분은 몇 초야?", "1킬로미터는 몇 미터야?", "영어로 사과는 뭐야?",
    "물의 화학식은?", "태양은 별이야?", "지구의 위성 이름은?", "윤년이 뭐야?",
    "광합성이 뭐야?", "명사가 뭐야?", "동사가 뭐야?", "비유가 뭐야?",
    "반의어가 뭐야?", "동의어가 뭐야?", "짝수가 뭐야?", "홀수가 뭐야?",
    "소수가 뭐야?", "분수가 뭐야?", "직각은 몇 도야?", "원의 반지름이 뭐야?",
    "정사각형이 뭐야?", "수증기는 어떤 상태야?", "얼음은 어떤 상태야?",
    "무지개는 왜 생겨?", "그림자는 왜 생겨?", "자석의 두 극은?",
    "키보드가 뭐야?", "마우스는 무엇에 써?", "CPU가 뭐야?", "RAM이 뭐야?",
    "파일 확장자가 뭐야?", "폴더가 뭐야?", "백업이 뭐야?", "압축 파일이 뭐야?",
    "알고리즘이 뭐야?", "변수가 뭐야?", "반복문이 뭐야?", "조건문이 뭐야?",
    "함수가 뭐야?", "버그가 뭐야?", "디버깅이 뭐야?", "오픈소스가 뭐야?",
    "버전 관리가 뭐야?", "읽기 전용이 무슨 뜻이야?",
)


# main(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def main() -> None:
    # load_rulebook()의 반환값을 rules에 대입합니다.
    rules = load_rulebook()
    # 아래 함수()의 반환값을 core에 대입합니다.
    core = Path("scripts/app/orchestrator/prompts/system_core.md").read_text(encoding="utf-8")
    # 오른쪽 식을 계산한 값을 system에 대입합니다.
    system = core + "\n\n" + rules.system_text
    # model에 문자열을 대입합니다.
    model = "qwen3.5:9b"
    # valid에 숫자 등 고정된 값을 대입합니다.
    valid = 0
    # latencies에 리스트(순서가 있고 수정 가능)을 대입합니다.
    latencies = []
    # for 반복문: 대상의 항목을 하나씩 (index, question)에 대입하며 아래 블록을 실행합니다.
    for index, question in enumerate(QUESTIONS, 1):
        # payload에 딕셔너리(키와 값의 쌍)을 대입합니다.
        payload = {"model": model, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": question}
        ], "stream": False, "think": False,
            "options": {"temperature": 0.3, "num_predict": 2000, "num_ctx": 16384}}
        # urllib.request.Request()의 반환값을 request에 대입합니다.
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        # time.monotonic()의 반환값을 start에 대입합니다.
        start = time.monotonic()
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with urllib.request.urlopen(request, timeout=60) as response:
            # json.load()의 반환값을 result에 대입합니다.
            result = json.load(response)
        # 오른쪽 식을 계산한 값을 elapsed에 대입합니다.
        elapsed = time.monotonic() - start
        # 리스트 끝에 항목 하나를 추가합니다.
        latencies.append(elapsed)
        # result['message']['content'].strip()의 반환값을 answer에 대입합니다.
        answer = result["message"]["content"].strip()
        # one_sentence()의 반환값을 passed에 대입합니다.
        passed = one_sentence(answer, rules.max_chars)
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        valid += passed
        # 값을 텍스트로 출력합니다.
        print(json.dumps({"index": index, "input": question, "output": answer,
                          "passed": passed, "seconds": round(elapsed, 3),
                          "input_tokens": result.get("prompt_eval_count"),
                          "output_tokens": result.get("eval_count")}, ensure_ascii=True),
              flush=True)
    # 값을 텍스트로 출력합니다.
    print(json.dumps({"total": len(QUESTIONS), "passed": valid, "model": model,
                      "rulebook_hash": rules.sha256,
                      "prompt_hash": hashlib.sha256(system.encode()).hexdigest(),
                      "p50_seconds": sorted(latencies)[24], "p95_seconds": sorted(latencies)[47]}))


# 이 파일을 실행 진입점으로 사용할 때만 아래 코드를 실행합니다. import할 때는 실행하지 않습니다.
if __name__ == "__main__":
    # main()을 호출해 작업을 수행합니다.
    main()
