"""
pytest 첫 예제: read_file 보안 테스트

pytest 규칙 (이것만 알면 시작할 수 있다)
- 파일 이름이 test_로 시작하면 테스트 파일
- 함수 이름이 test_로 시작하면 테스트 하나
- assert 조건  →  조건이 참이면 통과, 거짓이면 실패
- 실행: week1 폴더에서  pytest  (또는 자세히: pytest -v)

지난번 test_read_file.py(print로 눈으로 확인)와 다른 점
- 사람이 결과를 읽고 판단하지 않는다. "기대값"을 코드로 적어 두고 pytest가 자동으로 판정한다.
- 코드를 고친 뒤 pytest 한 번이면 보안 검사가 깨졌는지 바로 안다. (AI가 코드를 고쳐도 마찬가지)
"""

import os

import pytest

import step3_docs_server as server

DENIED = "접근 권한이 없습니다"
NOT_FOUND = "파일이 존재하지 않습니다"


# ---------------------------------------------------------------
# fixture: 테스트에 필요한 "준비물"을 만들어 주는 함수
#   테스트 함수의 인자 이름에 fixture 이름을 쓰면 pytest가 자동으로 실행해서 넣어 준다.
#
#   tmp_path    : pytest 기본 fixture. 테스트마다 새 임시 폴더를 만들어 주고, 끝나면 알아서 정리된다.
#   monkeypatch : 테스트 동안만 변수/환경변수를 바꿔치기하고, 끝나면 원래대로 되돌려 준다.
#
# 왜 필요하냐: 진짜 docs/ 폴더를 쓰면 누가 파일을 지우거나 추가할 때마다 테스트 결과가 바뀐다.
#             테스트는 "항상 같은 조건"에서 돌아야 한다.
# ---------------------------------------------------------------
@pytest.fixture
def docs_dir(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "hello.txt").write_text("안녕하세요", encoding="utf-8")
    (docs / "sub").mkdir()
    (docs / "sub" / "deep.txt").write_text("하위 폴더 파일", encoding="utf-8")

    # docs 밖에 있는 "비밀" 파일 (읽히면 안 됨)
    (tmp_path / "secret.env").write_text("OPENAI_API_KEY=sk-test", encoding="utf-8")
    # 이름이 docs로 "시작"하는 다른 폴더 (startswith 실수를 잡기 위한 함정)
    (tmp_path / "docs_secret").mkdir()
    (tmp_path / "docs_secret" / "x.txt").write_text("비밀", encoding="utf-8")

    # 테스트 동안만 서버의 DOCS_DIR을 임시 폴더로 바꿔치기
    monkeypatch.setattr(server, "DOCS_DIR", os.path.realpath(docs))
    return docs


# ---------------- 정상 동작 ----------------
def test_reads_file_in_docs(docs_dir):
    assert server.read_file("hello.txt") == "안녕하세요"


def test_reads_file_in_subfolder(docs_dir):
    assert server.read_file("sub/deep.txt") == "하위 폴더 파일"


def test_missing_file(docs_dir):
    assert server.read_file("nope.txt") == NOT_FOUND


def test_directory_is_not_a_file(docs_dir):
    assert server.read_file(".") == NOT_FOUND


# ---------------- 공격 차단 ----------------
# parametrize: 같은 테스트를 입력만 바꿔서 여러 번 돌린다. (for문 대신)
# 하나가 실패해도 나머지는 계속 돌고, 어떤 입력이 실패했는지 따로 보여 준다.
@pytest.mark.parametrize("path", [
    "../secret.env",             # 상위 폴더로 탈출
    "sub/../../secret.env",      # 들어갔다가 다시 탈출
    "/etc/passwd",               # 절대 경로
    "../docs_secret/x.txt",      # 이름이 docs로 시작하는 옆 폴더
])
def test_blocks_paths_outside_docs(docs_dir, path):
    result = server.read_file(path)
    assert result.startswith(DENIED)
    assert "sk-test" not in result  # 혹시라도 내용이 새어 나오지 않았는지


def test_blocks_symlink_to_outside(docs_dir):
    # docs 안에 있지만, 실제로는 docs 밖의 비밀 파일을 가리키는 바로가기(심볼릭 링크)
    os.symlink(docs_dir.parent / "secret.env", docs_dir / "innocent.txt")
    result = server.read_file("innocent.txt")
    assert result.startswith(DENIED)


# ---------------- list_docs ----------------
def test_list_docs(docs_dir):
    names = server.list_docs().split("\n")
    assert names == ["hello.txt", "sub"]
