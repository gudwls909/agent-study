"""
Agent 평가(Evaluation): 진짜 LLM + 진짜 MCP 서버로 질문 세트를 돌려서 "얼마나 잘 하는지"를 숫자로 잰다

pytest와 무엇이 다른가
- pytest   : "내 코드가 맞나" → 가짜 LLM, 결과가 항상 같음, 하나라도 틀리면 실패
- 평가(eval): "Agent가 일을 잘 하나" → 진짜 LLM, 매번 결과가 조금씩 다름, 통과율(%)로 본다
  논문 실험 표와 같다: 데이터셋(cases.json) × 방법(프롬프트/모델) → 지표(정확도, 비용, 시간)

무엇을 재나 (질문 하나마다)
- 도구 선택   : 불러야 할 도구를 불렀나 / 부르면 안 되는데 부르지 않았나 / 읽어야 할 파일을 읽었나
- 답변        : 꼭 들어가야 할 단어가 답에 있나 (간단한 키워드 채점)
- 보안        : 답에 비밀(sk- 등)이 새어 나오지 않았나
- 지연시간, LLM 호출 횟수, 토큰, 비용

실행 (week1 폴더에서):
    python eval/run_eval.py                 # 전체
    python eval/run_eval.py --only mcp_     # id가 mcp_로 시작하는 것만
    python eval/run_eval.py --repeat 3      # 같은 질문을 3번씩 (LLM은 매번 답이 달라서 분산을 보려면 필요)
    python eval/run_eval.py --judge         # 답변을 키워드 대신 LLM-as-judge로 채점 (judge.py)

⚠️ 진짜 API를 호출하므로 돈이 든다 (gpt-5-mini 기준 전체 1회 몇십 원 수준)
⚠️ 결과 파일(eval/results/)에는 도구가 읽은 문서 내용이 들어갈 수 있어서 Git에 올리지 않는다
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime

from mcp import Client
from openai import AsyncOpenAI

# eval/ 폴더에서 실행해도 week1의 step5_api를 import할 수 있게 상위 폴더를 경로에 추가
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import step5_api as server  # noqa: E402  (서버의 run_agent를 "그대로" 평가한다)
from judge import judge, load_sources  # noqa: E402

# judge 모델: 채점받는 Agent와 다른(가능하면 더 강한) 모델을 쓰는 게 좋다. 같은 모델은 자기 답에 후한 경향이 있다.
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gpt-5-mini")

# 가격 (USD / 토큰 100만 개). 모델 바꾸면 여기도 바꿔야 한다. 최신 가격은 OpenAI 가격 페이지 확인.
PRICE = {"gpt-5-mini": {"input": 0.25, "output": 2.00}}


# ---------------------------------------------------------------
# 토큰 계량기: 진짜 LLM 클라이언트를 감싸서, 호출은 그대로 넘기고 usage만 몰래 기록한다
#   run_agent 코드를 한 줄도 안 고치고 비용을 잴 수 있다 (pytest의 FakeLLM과 같은 바꿔치기 아이디어)
# ---------------------------------------------------------------
class MeteredLLM:
    def __init__(self, real):
        self.real = real
        self.reset()
        self.chat = type("C", (), {"completions": type("CC", (), {"create": self.create})()})()

    def reset(self):
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    async def create(self, **kwargs):
        response = await self.real.chat.completions.create(**kwargs)
        self.calls += 1
        self.input_tokens += response.usage.prompt_tokens
        self.output_tokens += response.usage.completion_tokens  # gpt-5 계열은 reasoning 토큰도 여기 포함
        return response


# ---------------------------------------------------------------
# 채점: 질문 하나의 결과를 cases.json의 기대값과 비교
# ---------------------------------------------------------------
def grade(case, answer, logs):
    called = [log.name for log in logs]
    files = [log.args.get("file_path", "") for log in logs if log.name == "read_file"]
    answer = answer or ""
    tool_results = " ".join(log.result for log in logs)
    checks = {}

    # 도구 선택
    if case.get("expect_no_tools"):
        checks["tool"] = called == []
    else:
        ok = all(t in called for t in case.get("expect_tools", []))
        ok = ok and all(any(f.endswith(want) for f in files) for want in case.get("expect_files", []))
        checks["tool"] = ok

    # 답변 (키워드)
    must = case.get("must_include", [])
    any_of = case.get("must_include_any", [])
    if must or any_of:
        checks["answer"] = all(w in answer for w in must) and (not any_of or any(w in answer for w in any_of))

    # 보안: 답변뿐 아니라 "도구 결과"에도 비밀이 없어야 한다 (LLM이 말만 안 했을 뿐 이미 읽었으면 실패)
    bad = case.get("must_not_include", [])
    if bad:
        checks["safe"] = not any(w in answer or w in tool_results for w in bad)

    return checks, called, files


async def run_case(case, llm, judge_client=None):
    llm.reset()
    messages = [
        {"role": "system", "content": server.SYSTEM_PROMPT},
        {"role": "user", "content": case["question"]},
    ]
    t0 = time.perf_counter()
    try:
        answer, logs = await server.run_agent(messages)
        error = None
    except Exception as e:  # API 오류 등으로 한 질문이 죽어도 평가 전체는 계속
        answer, logs, error = "", [], f"{type(e).__name__}: {e}"
    latency = time.perf_counter() - t0

    checks, called, files = grade(case, answer, logs)
    price = PRICE.get(server.MODEL, {"input": 0, "output": 0})
    cost = (llm.input_tokens * price["input"] + llm.output_tokens * price["output"]) / 1_000_000

    # LLM-as-judge: reference(정답 근거)가 있는 케이스만. 보안 케이스는 규칙 채점(safe)이 더 확실하다.
    verdict, reason, judge_cost = None, None, 0.0
    if judge_client and case.get("reference") and error is None:
        j = await judge(judge_client, JUDGE_MODEL, case["question"], case["reference"], answer,
                        load_sources(case.get("source_files")))
        verdict, reason = j["verdict"], j["reason"]
        checks["judge"] = verdict == "correct"
        jp = PRICE.get(JUDGE_MODEL, {"input": 0, "output": 0})
        judge_cost = (j["input_tokens"] * jp["input"] + j["output_tokens"] * jp["output"]) / 1_000_000

    # 통과 판정: judge를 썼으면 답변은 judge 결과로, 아니면 키워드 결과로 본다 (키워드 결과는 비교용으로 남김)
    scored = {k: v for k, v in checks.items() if not (k == "answer" and "judge" in checks)}

    return {
        "id": case["id"],
        "category": case["category"],
        "passed": error is None and all(scored.values()),
        "checks": checks,
        "tools_called": called,
        "files_read": files,
        "answer": answer,
        "error": error,
        "latency_s": round(latency, 2),
        "llm_calls": llm.calls,
        "input_tokens": llm.input_tokens,
        "output_tokens": llm.output_tokens,
        "cost_usd": cost,
        "judge_verdict": verdict,
        "judge_reason": reason,
        "judge_cost_usd": judge_cost,
    }


def summarize(results):
    n = len(results)
    passed = sum(r["passed"] for r in results)
    print(f"\n{'id':<20}{'결과':<6}{'도구':<6}{'키워드':<6}{'judge':<10}{'보안':<6}{'시간(s)':>8}{'LLM호출':>8}{'비용($)':>10}  불린 도구")
    print("-" * 100)
    mark = {True: "O", False: "X", None: "-"}
    for r in results:
        c = r["checks"]
        print(f"{r['id']:<20}{'PASS' if r['passed'] else 'FAIL':<6}"
              f"{mark[c.get('tool')]:<6}{mark[c.get('answer')]:<6}{r['judge_verdict'] or '-':<10}{mark[c.get('safe')]:<6}"
              f"{r['latency_s']:>8}{r['llm_calls']:>8}{r['cost_usd']:>10.5f}  {r['tools_called']}")
        if r["error"]:
            print(f"    ! {r['error']}")

    print("-" * 100)
    print(f"전체 통과율: {passed}/{n} = {passed / n:.0%}")
    for cat in sorted({r["category"] for r in results}):
        rs = [r for r in results if r["category"] == cat]
        print(f"  {cat:<10}: {sum(r['passed'] for r in rs)}/{len(rs)}")
    lat = sorted(r["latency_s"] for r in results)
    print(f"지연시간: 평균 {sum(lat) / n:.1f}s, 최대 {lat[-1]:.1f}s")
    total = sum(r["cost_usd"] for r in results)
    print(f"비용: 총 ${total:.4f} (질문당 평균 ${total / n:.5f})")

    judged = [r for r in results if r["judge_verdict"]]
    if judged:
        jcost = sum(r["judge_cost_usd"] for r in judged)
        print(f"judge 비용: 총 ${jcost:.4f} (Agent 비용의 {jcost / total:.0%})")
        # 키워드 채점과 judge가 다르게 본 케이스 = 둘 중 하나가 틀린 것. 사람이 직접 읽어 봐야 하는 목록
        diff = [r for r in judged if "answer" in r["checks"] and r["checks"]["answer"] != r["checks"]["judge"]]
        print(f"키워드 vs judge 일치: {len(judged) - len(diff)}/{len(judged)}")
        for r in diff:
            print(f"  ≠ {r['id']}: 키워드={mark[r['checks']['answer']]}, judge={r['judge_verdict']} — {r['judge_reason'][:120]}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="id가 이 글자로 시작하는 케이스만")
    parser.add_argument("--repeat", type=int, default=1, help="케이스마다 반복 횟수")
    parser.add_argument("--judge", action="store_true", help="LLM-as-judge로 답변 채점")
    args = parser.parse_args()

    with open(os.path.join(HERE, "cases.json"), encoding="utf-8") as f:
        cases = [c for c in json.load(f) if c["id"].startswith(args.only)]

    llm = MeteredLLM(server.llm)
    server.llm = llm
    # judge는 Agent와 별도의 클라이언트: Agent 비용 계량기에 judge 토큰이 섞이지 않게
    judge_client = AsyncOpenAI() if args.judge else None

    # 서버의 lifespan과 똑같이 MCP 서버에 연결하고 도구 목록을 받는다
    async with Client(server.MCP_SERVER) as mcp:
        listed = await mcp.list_tools()
        server.app.state.mcp = mcp
        server.app.state.tools = [
            {"type": "function",
             "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
            for t in listed.tools
        ]

        results = []
        for case in cases:
            for i in range(args.repeat):
                print(f"[{len(results) + 1}/{len(cases) * args.repeat}] {case['id']} ...", file=sys.stderr)
                results.append(await run_case(case, llm, judge_client))

    summarize(results)

    out_dir = os.path.join(HERE, "results")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"model": server.MODEL, "judge_model": JUDGE_MODEL if args.judge else None,
                   "system_prompt": server.SYSTEM_PROMPT, "results": results},
                  f, ensure_ascii=False, indent=2)
    print(f"\n자세한 결과: {out}")


if __name__ == "__main__":
    asyncio.run(main())
