import db

# temp_db fixture는 tests/conftest.py로 옮겼다 (test_agent_loop.py에서도 같이 쓰려고)


def test_new_session_is_empty(temp_db):
    # 저장한 적 없는 세션 → load_messages는 빈 리스트, session_exists는 False
    assert db.load_messages("new_session") == []
    assert not db.session_exists("new_session")


def test_save_and_load(temp_db):
    # 메시지 2개 저장 → 불러오면 같은 내용, 같은 순서
    db.save_messages("session1", [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "반가워요"},
    ])
    assert db.load_messages("session1") == [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "반가워요"},
    ]


def test_sessions_are_separated(temp_db):
    # 세션 A와 B에 각각 저장 → A를 불러오면 A 것만 나와야 함
    db.save_messages("A", [{"role": "user", "content": "A1"}])
    db.save_messages("B", [{"role": "user", "content": "B1"}])
    assert db.load_messages("A") == [{"role": "user", "content": "A1"}]


def test_korean_and_tool_messages(temp_db):
    # 한글 + tool_calls가 들어 있는 복잡한 메시지도 저장 → 불러오면 똑같은지
    db.save_messages("session2", [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function",
            "function": {"name": "read_file", "arguments": '{"file_path": "mcp.md"}'}}
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "MCP는 ..."},
    ])    
    assert db.load_messages("session2") == [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function",
            "function": {"name": "read_file", "arguments": '{"file_path": "mcp.md"}'}}
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "MCP는 ..."},
    ]

def test_sql_injection(temp_db):
    # SQL 삽입 공격 시도 → 세션 이름에 ' OR '1'='1 같은 걸 넣어도 다른 세션이 엉뚱하게 불러와지면 안 됨
    db.save_messages("safe_session", [{"role": "user", "content": "인젝션 테스트"}])
    malicious_session = "' OR '1'='1"
    assert db.load_messages(malicious_session) == []
    assert not db.session_exists(malicious_session)