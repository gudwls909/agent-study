"""
Step 3: Tool Calling — LLM이 Python 함수를 골라서 호출하게 만들기

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
llm = OpenAI()
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")


import asyncio
import sys
from mcp import Client, StdioServerParameters

HERE = os.path.dirname(os.path.abspath(__file__))

SERVER = StdioServerParameters(
    command=sys.executable,
    args=[os.path.join(HERE, "step3_docs_server.py")],
)

MAX_STEPS = 5  # 모델이 도구를 끝없이 부르는 사고를 막는 안전장치

messages = [{"role": "system", "content": "너는 간결하게 한국어로 답하는 조수야."}]

async def main():
    async with Client(SERVER) as client:
        listed = await client.list_tools()
        TOOLS = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in listed.tools
        ]
        while True:
                s = input("나: ")
                if s == "quit":
                    for m in messages:
                        print(m)
                    break
                messages.append({"role": "user", "content": s})
        
                # ---- Agent 루프: 모델이 도구 호출을 멈출 때까지 반복 ----
                for step in range(MAX_STEPS):
                    response = llm.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
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
                            # result = TOOL_FUNCTIONS[name](**args)
                            result = await client.call_tool(name, args)
                            result = result.content[0].text
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

asyncio.run(main())