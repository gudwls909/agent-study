"""
Agent 루프 테스트: 진짜 LLM 없이 run_agent()의 "제어 흐름"만 검사한다

왜 가짜 LLM을 쓰나
- 진짜 API는 돈이 들고, 느리고, 매번 답이 달라서(비결정적) assert를 쓸 수 없다.
- 여기서 검사하고 싶은 건 "LLM이 똑똑한가"가 아니라 "LLM이 이렇게 답하면 내 코드가 올바르게 반응하는가"다.
  (LLM 답변 품질은 다음 단계인 Agent 평가(Evaluation)에서 다룬다)

방법: monkeypatch로 두 가지를 바꿔치기한다
  server.llm            → 정해진 답을 순서대로 돌려주는 FakeLLM  (대본을 읽는 배우)
  server.app.state.mcp  → 정해진 결과를 돌려주는 FakeMCP        (MCP 서버 프로세스를 띄우지 않음)
"""

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

# step5_api를 import하는 순간 AsyncOpenAI()가 만들어지는데, 키가 없으면 에러가 난다.
# 가짜 키를 넣어 두면 .env가 없는 컴퓨터(예: GitHub CI)에서도 테스트가 돈다. 실제 호출은 하지 않는다.
os.environ.setdefault("OPENAI_API_KEY", "sk-fake-for-tests")

from openai.types.chat import ChatCompletion  # noqa: E402

import step5_api as server  # noqa: E402


# ---------------------------------------------------------------
# 가짜 응답 만들기
#   OpenAI SDK의 진짜 응답 타입(ChatCompletion)을 dict로 만든다.
#   그래서 run_agent 안의 msg.tool_calls, msg.model_dump(...)가 진짜와 똑같이 동작한다.
# ---------------------------------------------------------------
def answer(text):
    """도구 없이 바로 답하는 LLM 응답"""
    return _completion({"role": "assistant", "content": text})


def tool_call(name, args, call_id="call_1"):
    """도구를 부르는 LLM 응답"""
    return _completion({
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }],
    })


def _completion(message):
    return ChatCompletion.model_validate({
        "id": "fake", "object": "chat.completion", "created": 0, "model": "fake",
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
    })


# ---------------------------------------------------------------
# 가짜 LLM: 대본(responses)에 적힌 답을 순서대로 하나씩 돌려준다.
#   어떤 messages를 받았는지도 기록해 둔다 → "도구 결과가 LLM에게 전달됐나"를 검사할 수 있다.
# ---------------------------------------------------------------
class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.received = []  # 호출될 때마다 받은 messages의 복사본
        # run_agent는 llm.chat.completions.create(...)로 부르므로 같은 모양을 만들어 준다
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, model, messages, tools):
        self.received.append([dict(m) for m in messages])  # 복사: 나중에 messages가 바뀌어도 그때 모습 유지
        return self.responses.pop(0)


# 가짜 MCP: 도구 이름 → 결과 문자열. 결과 대신 Exception을 넣으면 그 예외를 던진다.
class FakeMCP:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        result = self.results[name]
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(content=[SimpleNamespace(text=result)])  # r.content[0].text 모양


@pytest.fixture
def agent(monkeypatch):
    """테스트에서 setup(llm_responses, tool_results)로 가짜를 설치한다."""
    def setup(llm_responses, tool_results=None):
        fake_llm = FakeLLM(llm_responses)
        fake_mcp = FakeMCP(tool_results or {})
        monkeypatch.setattr(server, "llm", fake_llm)
        # app.state에는 원래 mcp/tools가 없다(lifespan에서 만든다). raising=False: 없던 속성도 만들어 넣기
        monkeypatch.setattr(server.app.state, "mcp", fake_mcp, raising=False)
        monkeypatch.setattr(server.app.state, "tools", [], raising=False)
        return fake_llm, fake_mcp
    return setup


def run(messages):
    # run_agent는 async 함수라 그냥 부르면 실행되지 않는다. asyncio.run으로 끝까지 실행한다.
    return asyncio.run(server.run_agent(messages))


def start():
    return [{"role": "system", "content": "sys"}, {"role": "user", "content": "질문"}]


# ---------------- 1. 도구 없이 바로 답하는 경우 ----------------
def test_direct_answer(agent):
    fake_llm, fake_mcp = agent([answer("안녕하세요")])
    messages = start()

    result, logs = run(messages)

    assert result == "안녕하세요"
    assert logs == []
    assert fake_mcp.calls == []                 # 도구는 안 불렸고
    assert len(fake_llm.received) == 1          # LLM은 한 번만 불렸고
    assert messages[-1] == {"role": "assistant", "content": "안녕하세요"}  # 답이 기록에 남았다


# ---------------- 2. 도구 한 번 → 답 ----------------
def test_tool_then_answer(agent):
    fake_llm, fake_mcp = agent(
        [tool_call("read_file", {"file_path": "mcp.md"}, call_id="call_42"), answer("MCP는 도구 표준입니다")],
        {"read_file": "MCP 문서 내용"},
    )
    messages = start()

    result, logs = run(messages)

    assert result == "MCP는 도구 표준입니다"
    assert fake_mcp.calls == [("read_file", {"file_path": "mcp.md"})]  # LLM이 준 인자 그대로 도구에 전달

    # 기록 순서: system, user, assistant(tool_calls), tool, assistant(답)
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool", "assistant"]
    # tool 메시지의 id가 LLM이 준 id와 같아야 한다 (다르면 OpenAI가 400 에러를 낸다)
    assert messages[3] == {"role": "tool", "tool_call_id": "call_42", "content": "MCP 문서 내용"}

    # 두 번째 LLM 호출 때 도구 결과를 실제로 받았는가
    assert fake_llm.received[1][-1]["content"] == "MCP 문서 내용"

    assert len(logs) == 1 and logs[0].name == "read_file"


# ---------------- 3. 도구가 에러를 내도 루프는 계속된다 ----------------
def test_tool_error_is_returned_to_llm(agent):
    fake_llm, _ = agent(
        [tool_call("read_file", {"file_path": "x"}), answer("파일을 읽지 못했어요")],
        {"read_file": RuntimeError("MCP 연결 끊김")},
    )
    messages = start()

    result, _ = run(messages)

    assert result == "파일을 읽지 못했어요"     # 서버가 죽지 않고 끝까지 갔다
    assert "MCP 연결 끊김" in messages[3]["content"]  # 에러 내용이 tool 결과로 LLM에게 전달됐다


# ---------------- 4. 도구만 계속 부르면 MAX_STEPS에서 멈춘다 ----------------
def test_stops_at_max_steps(agent):
    # LLM이 영원히 도구만 부르는 상황 (실제로 가끔 생긴다: 같은 파일을 계속 다시 읽는 등)
    fake_llm, fake_mcp = agent(
        [tool_call("list_docs", {}) for _ in range(server.MAX_STEPS)],
        {"list_docs": "a.md"},
    )

    result, logs = run(start())

    assert "최대 단계" in result
    assert len(fake_llm.received) == server.MAX_STEPS  # 정확히 MAX_STEPS번만 LLM을 불렀다 (비용 상한)
    assert len(fake_mcp.calls) == server.MAX_STEPS


# ---------------- 5. 한 번에 도구 여러 개 (병렬 도구 호출) ----------------
def test_parallel_tool_calls(agent):
    # "mcp.md랑 agent_loop.md 둘 다 읽어줘" → LLM이 한 응답에 tool_calls 2개를 담아 보내는 경우
    two_calls = _completion({
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_a", "type": "function",
             "function": {"name": "read_file", "arguments": json.dumps({"file_path": "mcp.md"})}},
            {"id": "call_b", "type": "function",
             "function": {"name": "read_file", "arguments": json.dumps({"file_path": "agent_loop.md"})}},
        ],
    })
    # 파일 이름에 따라 다른 결과를 주기 위해 FakeMCP를 조금 바꾼 버전
    contents = {"mcp.md": "MCP 내용", "agent_loop.md": "루프 내용"}

    fake_llm, fake_mcp = agent([two_calls, answer("둘 다 읽었어요")])

    async def call_tool(name, args):
        fake_mcp.calls.append((name, args))
        return SimpleNamespace(content=[SimpleNamespace(text=contents[args["file_path"]])])
    fake_mcp.call_tool = call_tool

    messages = start()
    result, logs = run(messages)

    assert result == "둘 다 읽었어요"
    assert fake_mcp.calls == [
        ("read_file", {"file_path": "mcp.md"}),
        ("read_file", {"file_path": "agent_loop.md"}),
    ]
    # tool 메시지 2개가 각자 자기 id + 자기 결과를 들고 있어야 한다
    # (id가 뒤바뀌면 LLM은 mcp.md 내용을 agent_loop.md 것으로 착각한다)
    assert messages[3] == {"role": "tool", "tool_call_id": "call_a", "content": "MCP 내용"}
    assert messages[4] == {"role": "tool", "tool_call_id": "call_b", "content": "루프 내용"}
    # LLM 호출은 2번: 도구 2개를 부르는 데 1번 + 답하는 데 1번 (도구마다 LLM을 다시 부르지 않는다)
    assert len(fake_llm.received) == 2
    assert len(logs) == 2


# ---------------- 6. /chat 엔드포인트: 세션이 DB에 제대로 이어지는가 ----------------
# temp_db(conftest.py)와 agent 두 fixture를 같이 쓴다
def test_chat_continues_session(temp_db, agent):
    fake_llm, _ = agent([answer("안녕하세요"), answer("아까 인사하셨죠")])

    # HTTP 없이 엔드포인트 함수를 직접 부른다
    first = asyncio.run(server.chat(server.ChatRequest(message="안녕")))
    second = asyncio.run(server.chat(server.ChatRequest(message="내가 뭐라 했지?", session_id=first.session_id)))

    assert second.session_id == first.session_id
    assert second.answer == "아까 인사하셨죠"

    saved = server.db.load_messages(first.session_id)
    # system 메시지는 첫 요청 때 딱 한 번만 저장 (예전 버그: n을 system 추가 뒤에 재서 저장이 빠졌다)
    assert [m["role"] for m in saved] == ["system", "user", "assistant", "user", "assistant"]
    assert saved[0] == {"role": "system", "content": server.SYSTEM_PROMPT}

    # 두 번째 LLM 호출은 첫 대화를 전부 들고 갔어야 한다 = Agent가 "기억"한다
    assert fake_llm.received[1] == saved[:4]


def test_chat_new_sessions_are_separate(temp_db, agent):
    agent([answer("A"), answer("B")])

    a = asyncio.run(server.chat(server.ChatRequest(message="1")))
    b = asyncio.run(server.chat(server.ChatRequest(message="2")))  # session_id 없음 → 새 세션

    assert a.session_id != b.session_id
    assert len(server.db.load_messages(a.session_id)) == 3  # system, user, assistant
    assert len(server.db.load_messages(b.session_id)) == 3
