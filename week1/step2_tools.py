"""
Step 2: Tool Calling — LLM이 Python 함수를 골라서 호출하게 만들기

흐름
  1. 모델에게 "이런 도구들이 있어"라고 도구 설명서(tools)를 같이 보낸다
  2. 모델이 도구가 필요하다고 판단하면, 답 대신 "이 함수를 이 인자로 불러줘"(tool_calls)를 돌려준다
  3. 우리 코드가 그 함수를 실제로 실행한다   ← 모델은 함수를 직접 실행하지 못한다!
  4. 실행 결과를 role="tool" 메시지로 messages에 넣고 다시 모델을 부른다
  5. 모델이 더 이상 도구를 부르지 않고 텍스트로 답하면 끝

Voyager와 비교하면: 모델이 코드/스킬을 고르고 → 환경에서 실행 → 결과를 다시 프롬프트에 넣는 것과 같은 루프다.
"""

import json
import os
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI()
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")


# ---------------------------------------------------------------
# (1) 실제 도구: 평범한 Python 함수
# ---------------------------------------------------------------
def multiply(a: float, b: float) -> float:
    return a * b


def get_current_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


DOCS_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "docs"))
def read_file(file_path: str) -> str:
    full_path = os.path.realpath(os.path.join(DOCS_DIR, file_path))
    if os.path.commonpath([DOCS_DIR, full_path]) != DOCS_DIR:
        return "접근 권한이 없습니다: docs 폴더 안의 파일만 읽을 수 있습니다"
    if not os.path.isfile(full_path):
        return "파일이 존재하지 않습니다"
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


def list_docs() -> str:
    return "\n".join(os.listdir(DOCS_DIR)) 

# 모델이 부른 "이름"을 실제 함수로 연결하는 표
TOOL_FUNCTIONS = {
    "multiply": multiply,
    "get_current_time": get_current_time,
    "read_file": read_file,
    "list_docs": list_docs,
}


# ---------------------------------------------------------------
# (2) 도구 설명서: 모델은 이것만 보고 언제, 어떻게 쓸지 판단한다
#     parameters는 JSON Schema 형식 (인자 이름, 타입, 필수 여부)
# ---------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "multiply",
            "description": "두 수를 곱한다. 곱셈이 필요하면 직접 계산하지 말고 반드시 이 도구를 써라.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "첫 번째 수"},
                    "b": {"type": "number", "description": "두 번째 수"},
                },
                "required": ["a", "b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "현재 날짜와 시각을 알려준다.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "docs 폴더 안의 파일 경로를 받아서 파일 내용을 읽어온다. 경로는 docs 기준 상대 경로로 준다. 파일이 존재하지 않으면 '파일이 존재하지 않습니다' 를 반환한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "읽을 파일의 경로"},
                },
                "required": ["file_path"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_docs",
            "description": "docs 폴더 안의 파일 목록을 줄바꿈으로 구분된 문자열로 반환한다.",
            "parameters": {"type": "object", "properties": {}},
            "required": [],
        }
    },    
]

MAX_STEPS = 5  # 모델이 도구를 끝없이 부르는 사고를 막는 안전장치

messages = [{"role": "system", "content": "너는 간결하게 한국어로 답하는 조수야."}]

if __name__ == "__main__":
    while True:
        s = input("나: ")
        if s == "quit":
            for m in messages:
                print(m)
            break
        messages.append({"role": "user", "content": s})

        # ---- Agent 루프: 모델이 도구 호출을 멈출 때까지 반복 ----
        for step in range(MAX_STEPS):
            response = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
            msg = response.choices[0].message

            # 모델의 응답(도구 호출 요청 포함)도 기록에 남겨야 다음 요청에서 맥락이 이어진다
            messages.append(msg.model_dump(exclude_none=True))

            if not msg.tool_calls:
                # 도구 호출이 없으면 최종 답변
                print("답변:", msg.content)
                break

            # 모델이 요청한 도구들을 실제로 실행
            for call in msg.tool_calls:
                name = call.function.name
                args = json.loads(call.function.arguments)  # 인자는 JSON "문자열"로 온다
                print(f"  [도구 호출] {name}({args})")

                try:
                    result = TOOL_FUNCTIONS[name](**args)
                except Exception as e:
                    result = f"도구 실행 중 오류 발생: {e}"
                print(f"  [도구 결과] {result}")

                # 결과를 role="tool"로 돌려준다. tool_call_id로 "어느 호출의 결과인지" 짝을 맞춘다
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": str(result),
                })
        else:
            print("(최대 단계 수를 넘어서 중단)")
