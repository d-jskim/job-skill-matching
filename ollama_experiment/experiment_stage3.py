"""3단계 Curriculum Context 실험 (In-context evaluation).

- 1·2단계는 실행하지 않는다. 기존 결과 파일은 읽거나 쓰지 않는다.
- 총 모델 호출 44회: 모델 2 × (Single 10 JD × 2 cycle + Batch 1 × 2 cycle).
- 워밍업·사전측정 호출 없음.
- 모델 응답은 어떤 경우에도 수정·보정하지 않는다. 검증 결과만 기록한다.
- reference.json은 import하지 않으며, 프롬프트 오염 여부를 실행 시 검사한다.
"""

import sys

sys.dont_write_bytecode = True

import hashlib  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
from datetime import datetime  # noqa: E402
from time import perf_counter  # noqa: E402

from ollama import Client  # noqa: E402

from config_stage3 import (  # noqa: E402
    CONDITION, CURRICULUM_FILE, CYCLE_COUNT, DATA_FILE, INSTRUCTION, MODELS,
    OPTIONS, OUTPUT_SCHEMA, PROMPT_VERSION, REFERENCE_FORBIDDEN, RESULTS_DIR,
    TIMEOUT, batch_instruction, batch_schema, build_prompt,
)

SCORE_KEYS = ("AX", "DS", "LLM", "PA")
TOP1_VALUES = ("AX", "DS", "LLM", "PA", "NONE")


def ollama_ps_snapshot() -> str:
    """적재 상태(PROCESSOR/CONTEXT)를 문자열로 남긴다. 실패해도 실험은 계속한다."""
    try:
        out = subprocess.run(
            ["ollama", "ps"], capture_output=True, text=True, timeout=20
        )
        return out.stdout.strip()
    except Exception as error:  # noqa: BLE001
        return f"snapshot_failed: {type(error).__name__}: {error}"


def check_one(jd: dict, result) -> dict:
    """JD 1건의 형식·규칙 검증. 응답을 변경하지 않고 판정만 돌려준다."""
    checks = {"format_valid": False, "rules_valid": False, "errors": []}

    if not isinstance(result, dict):
        checks["errors"].append("결과가 객체가 아닙니다.")
        return checks
    if set(result) != set(OUTPUT_SCHEMA["required"]):
        checks["errors"].append("필수 필드 누락 또는 미지정 필드 존재.")
        return checks

    scores = {key: result[key] for key in SCORE_KEYS}
    if any(type(score) is not int or not 0 <= score <= 100 for score in scores.values()):
        checks["errors"].append("점수가 0~100 정수가 아닙니다.")
        return checks
    if not isinstance(result["jd_id"], str) or type(result["none"]) is not bool:
        checks["errors"].append("jd_id 또는 none 타입 오류.")
        return checks
    if not isinstance(result["top1"], str) or result["top1"] not in TOP1_VALUES:
        checks["errors"].append("top1 값이 허용 범위를 벗어났습니다.")
        return checks
    skills = result["evidence_skills"]
    if not isinstance(skills, list) or not all(
        isinstance(skill, str) and skill.strip() for skill in skills
    ):
        checks["errors"].append("evidence_skills 형식 오류.")
        return checks
    if not isinstance(result["reason"], str) or not result["reason"].strip():
        checks["errors"].append("reason 형식 오류.")
        return checks
    checks["format_valid"] = True

    rule_errors = []
    if result["jd_id"] != jd["jd_id"]:
        rule_errors.append(f'jd_id 불일치(기대 {jd["jd_id"]}, 응답 {result["jd_id"]}).')
    is_none = max(scores.values()) <= 40
    if result["none"] != is_none:
        rule_errors.append(f"none 값이 점수 기준과 불일치(기대 {is_none}).")
    if is_none:
        if result["top1"] != "NONE":
            rule_errors.append("모든 점수가 40 이하인데 top1이 NONE이 아닙니다.")
    elif result["top1"] not in scores or scores[result["top1"]] != max(scores.values()):
        rule_errors.append("top1이 최고점 직무와 일치하지 않습니다.")
    checks["rules_valid"] = not rule_errors
    checks["errors"] = rule_errors
    return checks


def call_model(client, model, jds, is_batch, cycle, curriculum, curriculum_sha, result_file):
    inputs = [{"jd_id": item["jd_id"], "jd_text": item["jd_text"]} for item in jds]
    instruction = batch_instruction() if is_batch else INSTRUCTION
    schema = batch_schema(len(jds)) if is_batch else OUTPUT_SCHEMA
    payload = json.dumps(inputs if is_batch else inputs[0], ensure_ascii=False)
    prompt = build_prompt(instruction, curriculum, payload)

    # Reference 격리 검사: 프롬프트에 참고값이 섞이면 즉시 중단한다.
    lowered = prompt.lower()
    for token in REFERENCE_FORBIDDEN:
        if token in lowered:
            raise SystemExit(f"Reference 오염 감지: 프롬프트에 '{token}' 포함")

    record_id = [item["jd_id"] for item in jds] if is_batch else jds[0]["jd_id"]
    record = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "model": model,
        "evaluation_type": "batch" if is_batch else "single",
        "condition": CONDITION,
        "cycle": cycle,
        "jd_id": record_id,
        "prompt_version": PROMPT_VERSION + ("-batch" if is_batch else "-single"),
        "options": OPTIONS,
        "output_schema": schema,
        "prompt": prompt,
        "curriculum_sha256": curriculum_sha,
        "curriculum_chars": len(curriculum),
        "success": False, "call_success": False,
        "format_valid": None, "rules_valid": None, "per_jd_rules": None,
        "error": None, "raw_response": "", "parsed_result": None,
        "elapsed_seconds": None, "prompt_eval_count": None, "eval_count": None,
        "eval_duration": None, "load_duration": None, "done_reason": None,
        "tokens_per_second": None, "evidence_in_jd": None, "ollama_ps": None,
    }

    start = perf_counter()
    stage = "model_call"
    try:
        response = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=False, format=schema, options=OPTIONS, keep_alive="30m",
        )
        record["call_success"] = True
        record["elapsed_seconds"] = round(perf_counter() - start, 4)
        record["raw_response"] = response.message.content or ""
        for field in ("prompt_eval_count", "eval_count", "eval_duration",
                      "load_duration", "done_reason"):
            record[field] = getattr(response, field, None)
        if record["eval_duration"] and record["eval_count"] is not None:
            record["tokens_per_second"] = round(
                record["eval_count"] / (record["eval_duration"] / 1e9), 2
            )

        stage = "json_parse"
        parsed = json.loads(record["raw_response"])
        record["parsed_result"] = parsed

        stage = "validation"
        if record["done_reason"] == "length":
            raise ValueError("출력 토큰 한도(num_predict)에 도달했습니다.")
        results = parsed["results"] if is_batch else [parsed]
        if not isinstance(results, list) or len(results) != len(jds):
            raise ValueError(
                f"JD 결과 개수 불일치(기대 {len(jds)}, 응답 "
                f"{len(results) if isinstance(results, list) else 'N/A'})."
            )

        per_jd, evidence = {}, {}
        for jd, result in zip(jds, results):
            checks = check_one(jd, result)
            per_jd[jd["jd_id"]] = checks
            if checks["format_valid"]:
                evidence[jd["jd_id"]] = {
                    skill: skill in jd["jd_text"] for skill in result["evidence_skills"]
                }
        record["per_jd_rules"] = per_jd
        record["evidence_in_jd"] = evidence
        record["format_valid"] = all(v["format_valid"] for v in per_jd.values())
        record["rules_valid"] = all(v["rules_valid"] for v in per_jd.values())
        record["success"] = record["format_valid"] and record["rules_valid"]
        if not record["success"]:
            bad = {k: v["errors"] for k, v in per_jd.items() if v["errors"]}
            record["error"] = f"validation: {json.dumps(bad, ensure_ascii=False)}"
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001
        record["error"] = f"{stage}: {type(error).__name__}: {error}"
    if record["elapsed_seconds"] is None:
        record["elapsed_seconds"] = round(perf_counter() - start, 4)
    record["ollama_ps"] = ollama_ps_snapshot()

    with result_file.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")

    label = ",".join(record_id) if is_batch else record_id
    print(
        f"{model} | {record['evaluation_type']} | cycle={cycle} | {label} | "
        f"call={record['call_success']} fmt={record['format_valid']} "
        f"rules={record['rules_valid']} success={record['success']} | "
        f"in={record['prompt_eval_count']} out={record['eval_count']} "
        f"{record['elapsed_seconds']}s",
        flush=True,
    )
    if record["error"]:
        print(f"  오류: {record['error'][:400]}", flush=True)
    return record["success"]


def main():
    with DATA_FILE.open(encoding="utf-8") as file:
        dataset = json.load(file)
    if [jd["jd_id"] for jd in dataset] != [f"JD{i:02d}" for i in range(1, 11)]:
        raise SystemExit("데이터는 JD01~JD10 순서의 10개여야 합니다.")
    if any(not isinstance(jd["jd_text"], str) or not jd["jd_text"].strip() for jd in dataset):
        raise SystemExit("JD 원문이 비어 있습니다.")

    curriculum = CURRICULUM_FILE.read_text(encoding="utf-8")
    if not curriculum.strip():
        raise SystemExit("curriculum_context.md가 비어 있습니다.")
    curriculum_sha = hashlib.sha256(curriculum.encode("utf-8")).hexdigest()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d_%H%M%S_%f}"
    single_file = RESULTS_DIR / f"stage3-curriculum-single_{stamp}.jsonl"
    batch_file = RESULTS_DIR / f"stage3-curriculum-batch_{stamp}.jsonl"
    for path in (single_file, batch_file):
        if path.exists():
            raise SystemExit(f"기존 파일을 덮어쓸 수 없습니다: {path}")

    print("=" * 78)
    print("3단계 Curriculum Context 실험 (In-context evaluation)")
    print(f"커리큘럼: {CURRICULUM_FILE.name} / {len(curriculum)}자 / sha256={curriculum_sha[:16]}")
    print(f"옵션: {json.dumps(OPTIONS)}")
    print(f"Single 결과: {single_file.name}")
    print(f"Batch  결과: {batch_file.name}")
    print(f"예정 호출 수: {len(MODELS)} × ({len(dataset)} × {CYCLE_COUNT} + {CYCLE_COUNT}) = "
          f"{len(MODELS) * (len(dataset) * CYCLE_COUNT + CYCLE_COUNT)}회")
    print("=" * 78, flush=True)

    client = Client(host="http://127.0.0.1:11434", timeout=TIMEOUT)
    calls = 0
    started = perf_counter()

    for model in MODELS:
        print(f"\n---------- {model} : Curriculum Single ----------", flush=True)
        for cycle in range(1, CYCLE_COUNT + 1):
            for jd in dataset:
                call_model(client, model, [jd], False, cycle,
                           curriculum, curriculum_sha, single_file)
                calls += 1

        print(f"\n---------- {model} : Curriculum Batch ----------", flush=True)
        for cycle in range(1, CYCLE_COUNT + 1):
            call_model(client, model, dataset, True, cycle,
                       curriculum, curriculum_sha, batch_file)
            calls += 1

        try:
            client.generate(model=model, keep_alive=0)
            print(f"{model} 언로드 완료", flush=True)
        except Exception as error:  # noqa: BLE001
            print(f"{model} 언로드 실패: {error}", flush=True)

    print("\n" + "=" * 78)
    print(f"완료. 모델 호출 {calls}회 / 총 {perf_counter() - started:.1f}초")
    print(f"Single: {single_file}")
    print(f"Batch : {batch_file}")
    print("=" * 78, flush=True)


if __name__ == "__main__":
    main()
