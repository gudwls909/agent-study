"""
Step 5-2: 대화 기록 저장소 (DB 담당 모듈)

API 서버(step5_api.py)는 DB를 직접 만지지 않고 이 파일의 함수만 부른다.
  → 나중에 SQLite를 PostgreSQL로 바꿔도 이 파일만 고치면 된다. (실무에서 흔한 구조: "저장소 계층")

메시지를 열(column)마다 쪼개지 않고 dict 전체를 JSON 문자열로 통째로 저장한다.
  이유: tool_calls, tool_call_id처럼 메시지 종류마다 들어 있는 항목이 달라서,
        열을 다 만들면 복잡해진다. 연습 단계에서는 이게 가장 단순하다.
"""

import json
import os
import sqlite3

# DB_PATH 환경변수가 있으면 그 위치를, 없으면 이 파일 옆의 chat.db를 쓴다.
# (Docker에서는 Dockerfile의 ENV DB_PATH=/data/chat.db 가 적용된다)
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat.db"))


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """테이블이 없으면 만든다. 서버 시작할 때 한 번 부른다."""
    with _connect() as conn:  # with 블록이 끝나면 자동으로 commit 된다
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                data       TEXT NOT NULL,                  -- 메시지 dict 전체를 JSON 문자열로
                created_at TEXT DEFAULT CURRENT_TIMESTAMP  -- 저장된 시각 (자동 기록)
            )
        """)
        # 인덱스: 책 뒤의 "찾아보기"와 같다. session_id로 검색할 때 전체를 다 뒤지지 않게 해 준다.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id)")


def session_exists(session_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM messages WHERE session_id = ? LIMIT 1", (session_id,)).fetchone()
    return row is not None


def load_messages(session_id: str) -> list[dict]:
    """이 세션의 메시지들을 저장된 순서대로 dict 리스트로 돌려준다. 없으면 빈 리스트."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT data FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
    return [json.loads(r[0]) for r in rows]  # JSON 문자열 → dict


def save_messages(session_id: str, messages: list[dict]) -> None:
    """메시지 여러 개를 한 번에 저장한다."""
    with _connect() as conn:
        conn.executemany(  # executemany: 같은 INSERT를 여러 값으로 반복
            "INSERT INTO messages (session_id, data) VALUES (?, ?)",
            [(session_id, json.dumps(m, ensure_ascii=False)) for m in messages],  # dict → JSON 문자열
        )


if __name__ == "__main__":
    # 간단한 자체 테스트: python db.py
    init_db()
    save_messages("test-session", [{"role": "user", "content": "안녕"}, {"role": "assistant", "content": "반가워요"}])
    print("존재?", session_exists("test-session"), "/ 없는 세션:", session_exists("nope"))
    print("불러오기:", load_messages("test-session"))
