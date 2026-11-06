"""
Step 4: FastAPI — 터미널에서만 쓰던 Agent를 "웹 API 서버"로 만들기

지금까지:  사람이 터미널에서 input()으로 직접 입력  → 나 혼자만 쓸 수 있다
이제부터:  다른 프로그램(웹 화면, 슬랙 봇, 사내 시스템...)이 HTTP 요청으로 Agent를 호출한다

    [웹 화면/슬랙/다른 서비스] --HTTP POST /chat--> [이 서버: FastAPI + Agent] --MCP--> [docs 서버]
                                                           |
                                                           +--> OpenAI

용어
- HTTP 요청: 웹 브라우저가 웹사이트에 접속할 때 쓰는 그 방식. GET(조회), POST(보내서 처리) 등이 있다.
- 엔드포인트(endpoint): 서버가 받는 주소 하나하나. 여기서는 GET /health, POST /chat 두 개.
- JSON: 요청/응답 데이터 형식. Python dict와 거의 같은 모양.

실행:  uvicorn step4_api:app --port 8000
       (uvicorn = FastAPI 앱을 실제로 띄워 주는 웹 서버 프로그램)
"""

import json
import os
import sys
import uuid
import db
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from mcp import Client, StdioServerParameters
from openai import AsyncOpenAI
from pydantic import BaseModel

load_dotenv()
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
MAX_STEPS = 5
SYSTEM_PROMPT = "너는 간결하게 한국어로 답하는 조수야"

# AsyncOpenAI: await로 호출하는 OpenAI 클라이언트.
# 서버는 여러 요청을 동시에 처리해야 한다. 동기 버전을 쓰면 한 사람의 LLM 응답을 기다리는 동안
# 서버 전체가 멈춰서 다른 사람 요청을 못 받는다.
llm = AsyncOpenAI()

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER = StdioServerParameters(
    command=sys.executable,
    args=[os.path.join(HERE, "step3_docs_server.py")],
)

# 세션별 대화 기록 (session_id -> messages 리스트)
# ⚠️ 그냥 메모리(dict)에 들고 있으므로 서버를 재시작하면 전부 사라진다 → Step 5에서 DB로 바꾼다
# SESSIONS: dict[str, list] = {}


# ---------------------------------------------------------------
# (1) 서버 시작/종료 시 할 일 (lifespan)
#     MCP 서버 연결은 요청마다 새로 맺으면 느리니까, 서버가 켜질 때 한 번만 연결해 두고 계속 쓴다.
# ---------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with Client(MCP_SERVER) as mcp:
        listed = await mcp.list_tools()
        app.state.mcp = mcp
        app.state.tools = [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.input_schema},
            }
            for t in listed.tools
        ]
        print("MCP 도구 로드:", [t.name for t in listed.tools], file=sys.stderr)
        db.init_db()  # 서버 시작 시 DB 초기화
        yield  # ← 여기서 서버가 요청을 받기 시작한다. 서버가 꺼지면 yield 아래로 내려오며 연결을 닫는다.


app = FastAPI(title="Docs Agent API", lifespan=lifespan)


# ---------------------------------------------------------------
# (2) 요청/응답 형식 정의 (Pydantic 모델)
#     FastAPI가 이걸 보고 들어온 JSON을 자동으로 검사한다. message가 빠져 있으면 422 에러를 알아서 돌려준다.
# ---------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None  # 없으면 새 대화를 시작한다


class ToolCallLog(BaseModel):
    name: str
    args: dict
    result: str


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    tool_calls: list[ToolCallLog]  # 어떤 도구를 불렀는지도 같이 돌려준다 (디버깅/추적용)


# ---------------------------------------------------------------
# (3) Agent 루프 — Step 3에서 while/input() 부분만 빼고 함수로 만든 것
# ---------------------------------------------------------------
async def run_agent(messages: list) -> tuple[str, list[ToolCallLog]]:
    logs: list[ToolCallLog] = []
    for _ in range(MAX_STEPS):
        response = await llm.chat.completions.create(model=MODEL, messages=messages, tools=app.state.tools)
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return msg.content, logs

        for call in msg.tool_calls:
            name = call.function.name
            args = json.loads(call.function.arguments)
            try:
                r = await app.state.mcp.call_tool(name, args)
                result = r.content[0].text
            except Exception as e:
                result = f"도구 실행 중 오류 발생: {e}"
            logs.append(ToolCallLog(name=name, args=args, result=result[:200]))
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    return "(최대 단계 수를 넘어서 중단)", logs


# ---------------------------------------------------------------
# (4) 엔드포인트
# ---------------------------------------------------------------
@app.get("/health")
async def health():
    """서버가 살아 있는지 확인용. 실무에서 모니터링 시스템이 주기적으로 찔러 본다."""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())  # uuid4: 겹치지 않는 랜덤 ID 생성
    # messages = SESSIONS.setdefault(session_id, [{"role": "system", "content": SYSTEM_PROMPT}])
    messages = db.load_messages(session_id)
    n = len(messages)
    if not messages:
        messages.append({"role": "system", "content": SYSTEM_PROMPT})
    messages.append({"role": "user", "content": req.message})
    answer, logs = await run_agent(messages)
    db.save_messages(session_id, messages[n:])  # 새로 추가된 메시지만 DB에 저장
    return ChatResponse(session_id=session_id, answer=answer, tool_calls=logs)


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """특정 세션의 대화 기록을 조회한다. 없으면 404 에러."""
    # if session_id not in SESSIONS:
    if not db.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    # return {"session_id": session_id, "messages": SESSIONS[session_id]}
    return {"session_id": session_id, "messages": db.load_messages(session_id)}
