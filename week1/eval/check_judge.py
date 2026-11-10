"""
judge를 믿기 전에, judge부터 평가한다 ("채점자 채점")

judge_check.json: 사람이 미리 정답 라벨(correct/partial/incorrect)을 붙여 둔 답변들.
  일부러 키워드 채점이 틀리는 함정을 넣었다: 부정문, 바꿔 말하기, 길지만 틀린 답, 지어낸 내용, 채점자 조작 시도.
judge의 판정이 사람 라벨과 얼마나 일치하는지 보고, 충분히 높을 때만 run_eval.py --judge 결과를 믿는다.

실행 (week1 폴더에서):
    python eval/check_judge.py              # 1번씩
    python eval/check_judge.py --repeat 3   # judge도 매번 판정이 다를 수 있다 → 일관성 확인
"""

import argparse
import asyncio
import json
import os
import sys
from collections import Counter

from dotenv import load_dotenv
from openai import AsyncOpenAI

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
load_dotenv(os.path.join(os.path.dirname(HERE), ".env"))

from judge import judge, load_sources  # noqa: E402

JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gpt-5-mini")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()

    with open(os.path.join(HERE, "judge_check.json"), encoding="utf-8") as f:
        items = json.load(f)

    client = AsyncOpenAI()
    # 질문끼리 서로 독립이라 동시에 보낸다 (gather). 순서대로 하면 10개 × 몇 초를 다 기다려야 한다.
    jobs = [judge(client, JUDGE_MODEL, it["question"], it["reference"], it["answer"],
                  load_sources(it.get("source_files")))
            for it in items for _ in range(args.repeat)]
    outputs = await asyncio.gather(*jobs)

    agree = 0
    print(f"judge 모델: {JUDGE_MODEL}\n")
    print(f"{'id':<20}{'사람':<11}{'judge':<34}일치")
    print("-" * 70)
    for i, it in enumerate(items):
        verdicts = [o["verdict"] for o in outputs[i * args.repeat:(i + 1) * args.repeat]]
        hits = sum(v == it["label"] for v in verdicts)
        agree += hits
        print(f"{it['id']:<20}{it['label']:<11}{', '.join(verdicts):<34}{hits}/{args.repeat}")
        if hits < args.repeat:
            wrong = next(o for o in outputs[i * args.repeat:(i + 1) * args.repeat] if o["verdict"] != it["label"])
            print(f"    이유: {wrong['reason'][:150]}")

    total = len(items) * args.repeat
    print("-" * 70)
    print(f"사람 라벨과 일치: {agree}/{total} = {agree / total:.0%}")
    print("judge 판정 분포:", dict(Counter(o["verdict"] for o in outputs)))


if __name__ == "__main__":
    asyncio.run(main())
