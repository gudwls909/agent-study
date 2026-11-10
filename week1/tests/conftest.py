"""
conftest.py: 여러 테스트 파일이 같이 쓰는 fixture를 두는 곳

pytest는 이 파일을 자동으로 읽는다. 따로 import하지 않아도
tests/ 안의 모든 테스트 파일에서 temp_db를 인자 이름으로 바로 쓸 수 있다.
"""

import pytest

import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    # db.DB_PATH를 임시 폴더 안의 파일로 바꿔치기 → 진짜 chat.db는 건드리지 않는다
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
