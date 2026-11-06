"""
Step 1: LLM에 요청 한 번 보내고 응답 받기

여기서 배우는 것
- SDK: openai 패키지. HTTP 요청을 직접 만들지 않고 Python 함수로 API를 호출하게 해준다.
- API 키를 코드에 쓰지 않고 .env 파일(환경변수)로 관리하는 법
- messages 구조: LLM은 "기억"이 없다. 매번 대화 전체를 리스트로 보내야 한다.
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

# .env 파일의 내용을 환경변수로 읽어온다 (OPENAI_API_KEY, OPENAI_MODEL)
load_dotenv()

# 클라이언트는 OPENAI_API_KEY 환경변수를 자동으로 찾는다
client = OpenAI()
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

messages = [
    {"role": "system", "content": "너는 간결하게 한국어를 말하는 조수야."}
]
while True:
    s = input("나: ")
    if s == "quit":
        break
    messages.append({"role": "user", "content": s})
    response = client.chat.completions.create(model=MODEL, messages=messages)
    answer = response.choices[0].message.content
    print("답변:", answer)
    messages.append({"role": "assistant", "content": answer})
    # 비용 감각을 위해 토큰 사용량도 확인해 두자 (실무에서 매우 중요)
    print("토큰 사용량:", response.usage.prompt_tokens, "입력 /", response.usage.completion_tokens, "출력")

# messages = [
#     # system: 모델의 역할/규칙. 사용자에게는 보이지 않는다.
#     {"role": "system", "content": "너는 간결하게 한국어로 답하는 조수야."},
#     # user: 사용자의 입력
#     {"role": "user", "content": "Tool Calling이 뭔지 두 문장으로 설명해 줘."},
# ]

# response = client.chat.completions.create(model=MODEL, messages=messages)

# # 응답 객체에서 실제 텍스트만 꺼낸다
# answer = response.choices[0].message.content
# print("답변:", answer)

