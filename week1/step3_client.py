"""
Step 3: MCP 클라이언트 — LLM 없이 MCP 서버에 직접 접속해서 도구 목록을 보고 실행해 보기

여기서 처음 보는 문법: async / await
- MCP 통신은 "요청 보내고 → 응답 올 때까지 기다리기"의 연속이라 비동기(async)로 작성한다.
- 지금은 이렇게만 이해하면 충분하다:
    async def main():  → "기다리는 작업이 들어 있는 함수"
    await xxx          → "xxx가 끝날 때까지 기다려"
    asyncio.run(main()) → 그 함수를 실행하는 시작 버튼
"""

import asyncio
import os
import sys

from mcp import Client, StdioServerParameters

HERE = os.path.dirname(os.path.abspath(__file__))

# "서버를 어떻게 띄울지"에 대한 설정.
# 클라이언트가 이 명령으로 서버 프로그램을 직접 실행하고, stdin/stdout으로 연결한다.
SERVER = StdioServerParameters(
    command=sys.executable,  # 지금 쓰는 python (agent-study 환경)
    args=[os.path.join(HERE, "step3_docs_server.py")],
)


async def main():
    async with Client(SERVER) as client:
        # 1) "무슨 도구 있어?"  — Step 2에서는 우리가 TOOLS를 직접 썼지만, 이제 서버에게 물어본다
        result = await client.list_tools()
        print("=== 서버가 알려준 도구 목록 ===")
        for tool in result.tools:
            print(f"- {tool.name}: {tool.description}")
            print(f"    입력 형식: {tool.input_schema}")

        # 2) "이 도구 실행해 줘"
        print("\n=== list_docs 호출 ===")
        r = await client.call_tool("list_docs", {})
        print(r.content[0].text)

        print("\n=== read_file('../.env') 호출 (막혀야 정상) ===")
        r = await client.call_tool("read_file", {"file_path": "../.env"})
        print(r.content[0].text)


asyncio.run(main())
