"""
Step 3: MCP 서버 — Step 2의 도구들을 "누구나 쓸 수 있는 표준 도구 서버"로 떼어내기

Step 2와 무엇이 다른가
- Step 2: 도구 함수 + 도구 설명서(TOOLS JSON) + Agent 루프가 한 파일에 붙어 있었다.
          다른 Agent(Claude Code 등)는 이 도구를 쓸 방법이 없다.
- Step 3: 도구만 이 서버에 둔다. MCP 클라이언트(우리 Agent, Claude Code, Cursor...)는
          서버에 접속해서 "무슨 도구 있어?"(list_tools) → "이거 실행해 줘"(call_tool)를 표준 방식으로 요청한다.

  USB에 비유하면: 도구마다 전용 케이블을 만들던 것(Step 2)을 USB 규격(MCP)으로 통일한 것.

중요한 주의점 (stdio 방식)
- 이 서버는 클라이언트와 표준 입출력(stdin/stdout)으로 대화한다.
- 그래서 서버 코드에서 print()를 쓰면 통신 내용이 깨진다! 디버깅 출력은 stderr로 보내야 한다.
"""

import os
import sys

from mcp.server.mcpserver import MCPServer  # mcp 1.x에서는 FastMCP라는 이름이었다

# 서버 이름: 클라이언트에게 "나는 docs 서버야"라고 소개할 때 쓰인다
mcp = MCPServer("docs")

DOCS_DIR = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs"))


# @mcp.tool() 한 줄이 Step 2의 TOOLS JSON 작업을 대신한다.
#   - 함수 이름          → 도구 이름
#   - 독스트링("""...""") → description
#   - 타입 힌트(str 등)   → parameters (JSON Schema 자동 생성)
@mcp.tool()
def read_file(file_path: str) -> str:
    """docs 폴더 안의 텍스트 파일을 읽는다. file_path는 docs 기준 상대 경로(예: notes.txt)."""
    full_path = os.path.realpath(os.path.join(DOCS_DIR, file_path))
    if os.path.commonpath([DOCS_DIR, full_path]) != DOCS_DIR:
        return "접근 권한이 없습니다: docs 폴더 안의 파일만 읽을 수 있습니다"
    if not os.path.isfile(full_path):
        return "파일이 존재하지 않습니다"
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


@mcp.tool()
def list_docs() -> str:
    """docs 폴더 안의 파일 이름 목록을 돌려준다. 어떤 파일이 있는지 모를 때 먼저 호출한다."""
    return "\n".join(sorted(os.listdir(DOCS_DIR)))


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """두 수를 곱한다 -- 곱셈이 필요하면 직접 계산하지 말고 반드시 이 도구를 써라."""
    return a * b


if __name__ == "__main__":
    print("docs MCP 서버 시작 (stdio)", file=sys.stderr)  # stdout이 아니라 stderr!
    mcp.run()  # 기본값 transport="stdio"
