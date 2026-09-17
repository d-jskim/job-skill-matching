"""gpt-5.6-luna 로 1·2·3단계를 실행한다 (외부 OpenAI API, 총 44회).

- 1단계 JD-only Single  : 10 JD x 2 cycle = 20회
- 2단계 JD-only Batch   : 1 x 2 cycle     =  2회
- 3단계 Curriculum Single: 10 JD x 2 cycle = 20회
- 3단계 Curriculum Batch : 1 x 2 cycle     =  2회
프롬프트와 스키마는 로컬 실험과 동일한 것을 config.py에서 가져온다.
모델 응답은 수정하거나 보정하지 않는다. 검증 판정만 따로 기록한다.
reference.json 은 import 하지 않는다.
"""

import sys

sys.dont_write_bytecode = True

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime  # noqa: E402
from time import perf_counter  # noqa: E402

from openai import OpenAI  # noqa: E402

from config_openai import (  # noqa: E402
    CURRICULUM_FILE, CYCLE_COUNT, DATA_FILE, JD_IDS, MODEL, OUTPUT_SCHEMA,
    REQUEST_PARAMS, RESULTS_DIR, build, response_format,
)
from experiment import check_one  # noqa: E402  (로컬과 동일한 검증 로직 재사용)


def call_model(client, jds, is_batch, condition, cycle, curriculum, result_file):
    inputs = [{"jd_id": item["jd_id"], "jd_text": item["jd_text"]} for item in jds]
    instruction, schema, version = build(condition, is_batch, jds)
    payload = json.dumps(inputs if is_batch else inputs[0], ensure_ascii=False)
    if condition == "curriculum":
        prompt = (instruction + "\n\n<CURRICULUM_CONTEXT>\n" + curriculum
                  + "\n</CURRICULUM_CONTEXT>\n\n" + payload)
    else:
        prompt = instruction + "\n\n" + payload

    lowered = prompt.lower()
    for token in ("reference_label", "reference_scores"):
        if token in lowered:
            raise SystemExit(f"Reference 오염 감지: '{token}'")

    fmt, stripped = response_format(schema, strict=True)
    record_id = [item["jd_id"] for item in jds] if is_batch else jds[0]["jd_id"]
    record = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "model": MODEL,
        "evaluation_type": "batch" if is_batch else "single",
        "condition": condition,
        "cycle": cycle,
        "jd_id": record_id,
        "prompt_version": version,
        "options": dict(REQUEST_PARAMS),
        "output_schema": fmt["json_schema"]["schema"],
        "strict_mode_used": True,
        "stripped_schema_keys": stripped,
        "prompt": prompt,
        "curriculum_sha256": (hashlib.sha256(curriculum.encode("utf-8")).hexdigest()
                              if condition == "curriculum" else None),
        "curriculum_chars": len(curriculum) if condition == "curriculum" else None,
        "success": False, "call_success": False,
        "format_valid": None, "rules_valid": None, "per_jd_rules": None,
        "error": None, "raw_response": "", "parsed_result": None,
        "elapsed_seconds": None,
        "prompt_eval_count": None, "eval_count": None, "reasoning_tokens": None,
        "total_tokens": None, "done_reason": None, "evidence_in_jd": None,
    }

    start = perf_counter()
    stage = "model_call"
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format=fmt,
            **REQUEST_PARAMS,
        )
        record["call_success"] = True
        record["elapsed_seconds"] = round(perf_counter() - start, 4)
        record["raw_response"] = response.choices[0].message.content or ""
        record["done_reason"] = response.choices[0].finish_reason
        usage = response.usage
        record["prompt_eval_count"] = usage.prompt_tokens
        record["eval_count"] = usage.completion_tokens
        record["total_tokens"] = usage.total_tokens
        details = getattr(usage, "completion_tokens_details", None)
        record["reasoning_tokens"] = getattr(details, "reasoning_tokens", None)

        record["format_valid"] = False
        stage = "json_parse"
        parsed = json.loads(record["raw_response"])
        record["parsed_result"] = parsed
        stage = "validation"
        if record["done_reason"] == "length":
            raise ValueError("출력 토큰 한도에 도달했습니다.")
        results = parsed["results"] if is_batch else [parsed]
        if not isinstance(results, list) or len(results) != len(jds):
            raise ValueError("JD 결과 개수가 일치하지 않습니다.")

        record["evidence_in_jd"] = {}
        record["per_jd_rules"] = {}
        for item, result in zip(jds, results):
            checks = check_one(item, result)
            record["per_jd_rules"][item["jd_id"]] = checks
            if checks["format_valid"]:
                record["evidence_in_jd"][item["jd_id"]] = {
                    skill: skill in item["jd_text"] for skill in result["evidence_skills"]
                }
        if is_batch:
            got = [r.get("jd_id") for r in results if isinstance(r, dict)]
            if sorted(got) != sorted(JD_IDS[:len(jds)]):
                record["per_jd_rules"]["_batch"] = {
                    "format_valid": True, "rules_valid": False,
                    "errors": [f"JD 집합 불일치: {got}"],
                }
        checks_all = record["per_jd_rules"].values()
        record["format_valid"] = all(c["format_valid"] for c in checks_all)
        record["rules_valid"] = all(c["rules_valid"] for c in checks_all)
        record["success"] = record["format_valid"] and record["rules_valid"]
        if not record["success"]:
            bad = {k: c["errors"] for k, c in record["per_jd_rules"].items() if c["errors"]}
            record["error"] = f"validation: {json.dumps(bad, ensure_ascii=False)}"
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001
        record["error"] = f"{stage}: {type(error).__name__}: {error}"
    if record["elapsed_seconds"] is None:
        record["elapsed_seconds"] = round(perf_counter() - start, 4)

    with result_file.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")

    label = ",".join(record_id) if is_batch else record_id
    print(f"{condition:10s} | {record['evaluation_type']:6s} | cycle={cycle} | {label} | "
          f"call={record['call_success']} fmt={record['format_valid']} "
          f"rules={record['rules_valid']} success={record['success']} | "
          f"in={record['prompt_eval_count']} out={record['eval_count']} "
          f"reason_tok={record['reasoning_tokens']} {record['elapsed_seconds']}s", flush=True)
    if record["error"]:
        print(f"  오류: {record['error'][:300]}", flush=True)
    return record


def main():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY 가 설정되지 않았습니다.")

    with DATA_FILE.open(encoding="utf-8") as file:
        dataset = json.load(file)
    if [jd["jd_id"] for jd in dataset] != JD_IDS:
        raise SystemExit("데이터는 JD01~JD10 순서의 10개여야 합니다.")

    curriculum = CURRICULUM_FILE.read_text(encoding="utf-8")
    if not curriculum.strip():
        raise SystemExit("curriculum_context.md 가 비어 있습니다.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d_%H%M%S_%f}"
    files = {
        ("jd_only", False): RESULTS_DIR / f"gpt56luna-jdonly-single_{stamp}.jsonl",
        ("jd_only", True): RESULTS_DIR / f"gpt56luna-jdonly-batch_{stamp}.jsonl",
        ("curriculum", False): RESULTS_DIR / f"gpt56luna-curriculum-single_{stamp}.jsonl",
        ("curriculum", True): RESULTS_DIR / f"gpt56luna-curriculum-batch_{stamp}.jsonl",
    }
    for path in files.values():
        if path.exists():
            raise SystemExit(f"기존 파일을 덮어쓸 수 없습니다: {path}")

    print("=" * 84)
    print(f"gpt-5.6-luna 1·2·3단계 실험 / {json.dumps(REQUEST_PARAMS)}")
    print(f"커리큘럼 {len(curriculum)}자 sha256={hashlib.sha256(curriculum.encode()).hexdigest()[:16]}")
    for (cond, is_b), path in files.items():
        print(f"  {cond:10s} {'batch' if is_b else 'single':6s} -> {path.name}")
    print(f"예정 호출 수: 20 + 2 + 20 + 2 = 44회")
    print("=" * 84, flush=True)

    client = OpenAI(api_key=key, max_retries=3, timeout=300)
    calls, started = 0, perf_counter()
    totals = {"in": 0, "out": 0, "reason": 0}

    for condition in ("jd_only", "curriculum"):
        cur = curriculum if condition == "curriculum" else ""
        print(f"\n---------- {condition} : Single ----------", flush=True)
        for cycle in range(1, CYCLE_COUNT + 1):
            for jd in dataset:
                rec = call_model(client, [jd], False, condition, cycle, cur,
                                 files[(condition, False)])
                calls += 1
                totals["in"] += rec["prompt_eval_count"] or 0
                totals["out"] += rec["eval_count"] or 0
                totals["reason"] += rec["reasoning_tokens"] or 0
        print(f"\n---------- {condition} : Batch ----------", flush=True)
        for cycle in range(1, CYCLE_COUNT + 1):
            rec = call_model(client, dataset, True, condition, cycle, cur,
                             files[(condition, True)])
            calls += 1
            totals["in"] += rec["prompt_eval_count"] or 0
            totals["out"] += rec["eval_count"] or 0
            totals["reason"] += rec["reasoning_tokens"] or 0

    cost = totals["in"] / 1e6 * 0.20 + totals["out"] / 1e6 * 1.20
    print("\n" + "=" * 84)
    print(f"완료. 호출 {calls}회 / {perf_counter() - started:.1f}초")
    print(f"토큰: 입력 {totals['in']:,} / 출력 {totals['out']:,} "
          f"(그중 reasoning {totals['reason']:,})")
    print(f"예상 비용: ${cost:.4f}")
    for path in files.values():
        print(f"  {path}")
    print("=" * 84, flush=True)


if __name__ == "__main__":
    main()
