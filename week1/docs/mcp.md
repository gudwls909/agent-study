# MCP (Model Context Protocol)

MCP는 AI 애플리케이션이 외부 도구와 데이터에 접근하는 표준 규격이다.

- MCP 서버: 도구(tool)를 제공한다. 예) 문서 읽기, DB 조회
- MCP 클라이언트: 서버에 접속해 list_tools로 도구를 발견하고 call_tool로 실행한다.

도구를 MCP 서버로 분리하면, 같은 서버를 여러 Agent(직접 만든 Agent, Claude Code 등)가
코드 수정 없이 공유할 수 있다. stdio 방식에서는 stdout이 통신 채널이므로
서버 코드의 로그는 반드시 stderr로 출력해야 한다.
