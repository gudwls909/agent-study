"""
Step 5-1: SQL 기초 — Agent와 상관없이 DB만 먼저 만져 보기

DB(데이터베이스)를 엑셀에 비유하면
- DB 파일(practice.db)  = 엑셀 파일 하나
- 테이블(table)         = 시트 하나        (예: messages 시트)
- 열(column)            = 시트의 열 제목   (id, session_id, role, content ...)
- 행(row)               = 한 줄의 데이터   (메시지 하나)

SQL = DB에게 일을 시키는 언어. 오늘 쓰는 건 4개뿐:
  CREATE TABLE  시트 만들기
  INSERT        행 추가
  SELECT        행 조회
  DELETE        행 삭제

실행: python step5_db_basics.py   (실행할 때마다 practice.db를 새로 만든다)
"""

import os
import sqlite3  # SQLite: 설치 필요 없는 파일 하나짜리 DB. Python에 기본 포함.

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "practice.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)  # 연습용이니 매번 깨끗하게 시작

conn = sqlite3.connect(DB_PATH)  # DB 파일 열기 (없으면 새로 만든다)

# ---- 1) CREATE TABLE: 시트(테이블) 만들기 ----
conn.execute("""
    CREATE TABLE messages (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,  -- 행 번호. 자동으로 1, 2, 3... 증가
        session_id TEXT NOT NULL,                      -- 어느 대화인지. NOT NULL = 비워 두면 안 됨
        role       TEXT NOT NULL,                      -- system / user / assistant / tool
        content    TEXT                                -- 메시지 내용
    )
""")

# ---- 2) INSERT: 행 추가 ----
# 값 자리에 ?를 쓰고, 실제 값은 뒤에 튜플로 따로 넘긴다. (이유는 맨 아래 '보안' 참고)
conn.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", ("abc", "user", "안녕"))
conn.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", ("abc", "assistant", "반가워요"))
conn.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", ("xyz", "user", "다른 대화"))
conn.commit()  # ★ commit을 해야 실제로 파일에 저장된다. 안 하면 프로그램 끝날 때 날아간다.

# ---- 3) SELECT: 조회 ----
print("=== 전체 ===")
for row in conn.execute("SELECT id, session_id, role, content FROM messages"):
    print(row)  # 한 행이 튜플로 나온다: (1, 'abc', 'user', '안녕')

print("\n=== session_id가 'abc'인 것만, id 순서대로 ===")
rows = conn.execute(
    "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id", ("abc",)
).fetchall()  # fetchall: 결과를 리스트로 한 번에 받기
print(rows)

# ---- 4) DELETE: 삭제 ----
conn.execute("DELETE FROM messages WHERE session_id = ?", ("xyz",))
conn.commit()
count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]  # fetchone: 한 행만
print(f"\nxyz 삭제 후 남은 행 수: {count}")

conn.close()

# ---------------------------------------------------------------
# 보안: 왜 f-string으로 SQL을 만들지 않고 ?를 쓰나 (SQL 인젝션)
#
#   ❌ conn.execute(f"SELECT * FROM messages WHERE session_id = '{sid}'")
#      sid에 사용자가  ' OR '1'='1  을 넣으면 SQL이
#      ... WHERE session_id = '' OR '1'='1'  이 되어 "모든 사람의 대화"가 조회된다.
#
#   ✅ conn.execute("SELECT * FROM messages WHERE session_id = ?", (sid,))
#      ?를 쓰면 DB가 sid를 "그냥 글자"로만 취급한다. 무슨 값이 와도 SQL 명령이 되지 않는다.
#
#   Step 2의 경로 검사와 같은 원리: 외부(사용자, LLM)에서 온 값은 절대 그대로 믿지 않는다.
# ---------------------------------------------------------------
