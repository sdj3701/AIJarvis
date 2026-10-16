# Jarvis 코드로 시작하는 파이썬 공부

변수에 타입을 쓰지 않아도 된다는 것만 알고 있다면, 아래 순서로 읽어 보세요.
처음부터 앱 전체를 이해할 필요는 없습니다. 짧은 함수 하나에서 **입력 → 처리 → 반환값**을 따라가는 것이 첫 목표입니다.

## 1. 변수와 타입 힌트

```python
name = "자비스"       # 문자열: 글자 데이터
count = 3             # 정수
ratio = 0.5           # 실수
enabled = True        # 참. 거짓은 False
result = None         # 아직 값이 없음을 나타낼 때 쓰는 특별한 값

count = count + 1     # 오른쪽을 먼저 계산하고, 그 결과 4를 count에 대입
count += 1           # count = count + 1과 같은 숫자 증가 표현
```

`=`는 대입이고, `==`는 같은지 비교하는 연산자입니다.
파이썬에서는 **값(객체)에 타입이 있고 변수 이름이 그 값을 가리킵니다.**

```python
count: int = 3        # 이 프로젝트에서는 타입 힌트를 자주 사용합니다.
name: str = "자비스"  # 사람이 읽거나 검사 도구가 확인할 수 있도록 적는 설명입니다.
```

일반 파이썬은 `count: int`만 보고 다른 타입의 대입을 자동으로 막지 않습니다.
이 프로젝트의 Pydantic 모델처럼 타입 정보를 읽어 실제 검증을 수행하는 라이브러리도 있습니다.

| 표기 | 읽는 방법 |
| --- | --- |
| `str`, `int`, `float`, `bool` | 문자열, 정수, 실수, 참/거짓 |
| `bytes` | 파일·오디오·통신 등에 사용하는 바이트 데이터 |
| `list[str]` | 문자열을 담는 리스트 |
| `dict[str, int]` | 문자열 키에 정수 값을 연결하는 딕셔너리 |
| `tuple[str, ...]` | 문자열을 여러 개 담는 튜플. 여기서 `...`은 개수가 고정되지 않았다는 뜻 |
| `str \| None` | 문자열 또는 None |
| `Literal["day", "month"]` | 타입 검사 관점에서 두 문자열 중 하나 |
| `Any` | 정적 타입 검사에서 구체적인 타입 제약을 두지 않음 |

## 2. 주석, 들여쓰기, 함수

`#` 뒤의 설명은 실행되지 않습니다. 따옴표 안에 들어 있는 `#`은 문자열의 일부입니다.
함수·클래스·파일 처음의 `"""설명"""`은 **docstring**입니다. 일반 주석과 달리 `help()` 등으로 읽을 수 있는 설명 데이터입니다.

```python
def greet(name: str) -> str:
    message = f"안녕, {name}!"
    return message

answer = greet("자비스")
print(answer)  # 안녕, 자비스!
```

1. `def`는 함수를 정의합니다. 정의할 때 함수 본문이 바로 실행되지는 않습니다.
2. `name`은 입력을 받을 **매개변수**입니다. 호출할 때 넣은 `"자비스"`가 **인자**입니다.
3. `-> str`은 반환값이 문자열이라는 타입 힌트입니다.
4. 콜론 `:` 다음에 들여쓴 줄들이 함수 본문입니다. 이 프로젝트는 보통 공백 네 칸씩 들여씁니다.
5. `f"...{name}..."`은 변수 값을 문자열에 끼워 넣습니다.
6. `return`은 결과를 돌려주고 함수를 끝냅니다. 반환문 없이 끝나거나 `return`만 쓰면 None입니다.

`print()`는 화면에 출력하고, `return`은 호출한 코드에 결과를 전달합니다.

### 기본값과 별표

```python
def repeat(text: str, *, times: int = 2) -> str:
    return text * times

repeat("안녕")           # times를 생략하면 기본값 2
repeat("안녕", times=3)  # * 뒤 인자는 이름을 붙여 전달
```

`*args`는 여러 위치 인자를 튜플로, `**kwargs`는 여러 이름 인자를 딕셔너리로 모읍니다.
호출할 때 쓰는 `*values`, `**options`는 반대로 묶인 값을 펼쳐 인자로 전달합니다.

## 3. 조건문과 반복문

```python
text = "자비스"

if not text:
    print("빈 문자열입니다")
elif text == "자비스":
    print("호출어입니다")
else:
    print("다른 문장입니다")

for number in range(3):
    print(number)  # 0, 1, 2
```

`if`는 조건이 참인 분기를 실행합니다. `elif`는 앞 조건이 거짓일 때 추가로 검사하고, `else`는 앞 조건에 모두 해당하지 않을 때 실행합니다.
`None`, `False`, 숫자 0, 빈 문자열·리스트·딕셔너리 등은 조건식에서 거짓으로 취급됩니다.

| 표기 | 의미 |
| --- | --- |
| `==`, `!=` | 값이 같음, 다름 |
| `<`, `<=`, `>`, `>=` | 작음, 작거나 같음, 큼, 크거나 같음 |
| `and`, `or`, `not` | 논리 결합, 선택, 부정 |
| `value is None` | 값이 None 객체인지 확인 |
| `x in values` | 포함 여부. 딕셔너리에서는 키를 검사 |

`and`와 `or`는 필요한 곳까지만 평가하며, 항상 bool을 반환하는 것은 아닙니다.
예를 들어 `name or "기본 이름"`은 name이 빈 문자열이면 기본 이름을 선택합니다.

`while`은 조건이 참인 동안 반복합니다. `break`는 반복문을 끝내고, `continue`는 다음 회차로 넘어갑니다.
반복문에 붙은 `else`는 **break 없이 반복이 끝났을 때** 실행됩니다. if의 else와 구분하세요.

## 4. 여러 값을 담는 자료구조

```python
names = ["자비스", "사용자"]  # 리스트: 순서가 있고 수정 가능
names.append("친구")         # 끝에 추가
first = names[0]              # 인덱스는 0부터 시작
last = names[-1]              # -1은 마지막 항목
pair = names[0:2]             # 0 이상 2 미만 위치: 처음 두 항목

settings = {"name": "자비스", "enabled": True}  # 딕셔너리
name = settings["name"]                       # 없는 키면 KeyError
voice = settings.get("voice", False)          # 없으면 기본값 False

point = (10, 20)            # 튜플: 원소 구성을 수정할 수 없는 묶음
x, y = point               # 언패킹: x=10, y=20
unique = {"가", "가", "나"}  # 집합: 중복 제거, 순서에 의존하지 않기

lengths = [len(word) for word in names]  # 컴프리헨션: 항목별 계산을 모음
```

`other = names`는 리스트를 복사하지 않습니다. 두 이름이 같은 리스트를 가리키므로 한쪽으로 수정하면 다른 쪽에서도 보입니다.
`len()`은 항목 수, `min()`은 가장 작은 값, `max()`는 가장 큰 값을 구합니다.

## 5. 클래스, self, dataclass

```python
from dataclasses import dataclass

@dataclass
class Person:
    name: str
    age: int

    def introduce(self) -> str:
        return f"저는 {self.name}입니다."

person = Person(name="민수", age=20)
print(person.name)          # 객체의 속성 읽기
print(person.introduce())   # 객체의 메서드 호출
```

클래스는 관련 데이터와 동작의 설계도이고, `person`은 그 설계도로 만든 객체입니다.
클래스 안의 함수를 **메서드**, 객체에 저장한 값을 **속성**이라고 부릅니다.
`self`는 메서드를 호출한 객체를 가리킵니다. 위 호출에서는 person이 자동으로 전달됩니다.

`__init__`는 객체 초기화 시 실행되는 메서드입니다.
`@dataclass`는 필드 선언을 보고 `__init__` 같은 메서드를 자동으로 만들어 줍니다.
`@`로 시작하는 **데코레이터**는 함수나 클래스에 동작 또는 정보를 추가합니다.
`@property`를 붙인 메서드는 `person.name`처럼 괄호 없이 읽는 속성 형태로 사용할 수 있습니다.

`class Child(Parent)`는 부모 클래스의 기능을 물려받는 상속입니다.
`Protocol`은 객체가 갖춰야 할 메서드·속성의 규약을 타입 검사기에 알려 줍니다.
`TypedDict`는 일반 딕셔너리의 키와 값에 타입 힌트를 붙이는 데 사용합니다.

## 6. 파일, 모듈, 예외

```python
from pathlib import Path  # pathlib 모듈에서 Path라는 이름 가져오기

path = Path("example.txt")
try:
    with path.open("r", encoding="utf-8") as file:
        text = file.read()
except FileNotFoundError:
    text = "파일이 없습니다"
```

이 예시는 파일을 읽기만 합니다. `with`가 파일을 닫는 정리 작업을 맡습니다.
다른 객체의 with는 잠금 해제나 데이터베이스 처리처럼 그 객체가 정한 진입·종료 작업을 수행합니다.
`try`는 작업 시도, `except`는 지정한 오류 처리, `finally`는 블록을 벗어날 때의 정리입니다.
`raise ValueError(...)`는 잘못된 값을 예외로 알립니다.
`raise SystemExit(...)`는 프로그램 종료를 요청하는 예외이며, 반드시 프로그램 오류를 의미하지는 않습니다.

`import`는 모듈을 불러옵니다. 파이썬 파일 하나를 모듈로 사용할 수 있고, 모듈을 묶은 폴더는 패키지가 될 수 있습니다.
이 프로젝트에는 패키지마다 `__init__.py`가 있습니다.
`python -m app`은 `scripts/app/__main__.py`를 진입점으로 실행합니다.

## 7. 테스트 읽는 방법

```python
from app.voice.wake_match import normalize_spoken_command

def test_normalize():
    actual = normalize_spoken_command("자 비스!")
    assert actual == "자비스"
```

테스트는 **준비 → 실행 → 기대 결과 확인** 순서로 읽으세요.
`assert` 조건이 거짓이면 테스트가 실패합니다. 파이썬 최적화 실행에서는 assert가 제거될 수 있으므로 실제 보안 검증을 assert에만 맡기면 안 됩니다.
`pytest`는 이 프로젝트의 테스트 실행 도구입니다.

- `tmp_path`: pytest가 제공하는 테스트용 임시 폴더입니다.
- `monkeypatch`: 테스트 동안 함수·속성·환경 변수를 바꾸고 복원하는 도구입니다.
- `@pytest.fixture`: 여러 테스트에서 사용하는 준비 작업을 정의합니다.
- `@pytest.mark.parametrize`: 입력과 예상값을 바꿔 같은 테스트를 반복합니다.
- `pytest.raises(ValueError)`: 지정한 오류가 발생하는 것이 기대 결과입니다.

## 8. 추천 읽기 순서

링크는 이 문서를 기준으로 한 프로젝트 내부 경로입니다.

1. [호출어 처리](../scripts/app/voice/wake_match.py): 문자열, 조건문, 함수, 반환값을 익힙니다.
2. [호출어 테스트](../scripts/tests/unit/test_wake_match.py): 입력에 따른 결과를 확인합니다.
3. [문서 자르기](../scripts/app/rag/chunker.py): 리스트, while, 슬라이싱, dataclass를 익힙니다.
4. [시계](../scripts/app/core/clock.py): 클래스, self, Protocol과 실제 구현을 비교합니다.
5. [파일 저장](../scripts/app/core/atomic.py): Path, with, try/finally를 익힙니다.
6. [실행 시작점](../scripts/app/__main__.py): 명령줄 인자와 다른 함수로 일을 넘기는 흐름을 봅니다.
7. [구성 연결](../scripts/app/wiring.py): 기능별 객체가 어떻게 연결되는지 큰 흐름을 봅니다.
8. [대화 처리](../scripts/app/orchestrator/loop.py): 앞에서 배운 함수와 객체가 함께 동작하는 과정을 읽습니다.

### 첫 실습: 긴 문서가 어떻게 잘리는지 예상하기

`D:\Ai\Jarvis`에서 PowerShell로 다음 명령을 실행하면 파이썬 대화형 창이 열립니다.

```powershell
.\.venv\Scripts\python.exe
```

그 창에 아래 코드를 입력하세요.

```python
from app.rag.chunker import chunk_text

chunks = chunk_text("abcdefghij", chunk_chars=6, overlap_chars=2)
for chunk in chunks:
    print(chunk.ordinal, chunk.text, chunk.start_char, chunk.end_char)
```

예상 결과:

```text
0 abcdef 0 6
1 efghij 4 10
```

두 조각에 `ef`가 함께 들어 있습니다. `step = chunk_chars - overlap_chars`가 다음 조각의 시작을 4칸 이동시키기 때문입니다.
`overlap_chars=0`으로 바꾸면 무엇이 달라질지 먼저 예상한 뒤 실행해 보세요.
끝낼 때는 `exit()`를 입력하면 됩니다.

다음으로 위의 호출어 테스트를 실행해 볼 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m pytest scripts/tests/unit/test_wake_match.py
```

## 9. 나중에 만나면 찾아볼 문법

- `_name`: 내부 용도로 쓰겠다는 관례입니다. 접근을 강제로 막지는 않습니다.
- `yield`: 값을 하나 건네고 멈췄다가 다음 요청에서 이어서 실행합니다.
- `@contextmanager`: yield를 활용해 with 진입·종료 처리를 정의합니다.
- `lambda x: ...`: 짧은 함수를 식으로 만듭니다. 정렬 기준 등으로 전달할 때 자주 씁니다.
- `async def`, `await`: 기다리는 동안 다른 작업이 진행될 수 있도록 실행을 양보하는 비동기 문법입니다.
- `r"..."`: 역슬래시를 대체로 그대로 표현하는 raw 문자열입니다. 정규식에서 자주 보입니다.
- `re.compile(...)`: 문자열 패턴을 찾거나 바꾸기 위한 정규식을 준비합니다.
- `Path / "이름"`: Path 객체에서는 `/`가 숫자 나눗셈 대신 경로 결합을 수행합니다.
- `from __future__ import annotations`: 타입 힌트 평가를 지연하는 동작을 선택합니다.

모르는 문법이 나올 때마다 모든 개념을 외우기보다, 그 줄의 입력과 결과를 작은 예시로 확인해 보세요.
