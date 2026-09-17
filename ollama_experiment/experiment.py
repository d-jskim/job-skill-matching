import json
import hashlib
import argparse
from datetime import datetime
from time import perf_counter

from ollama import Client
from config import (
    DATA_FILE, RESULTS_DIR, MODELS, TIMEOUT, CYCLE_COUNT,
    PROMPT_VERSION, OPTIONS, INSTRUCTION, OUTPUT_SCHEMA,
    CURRICULUM_FILE, PROMPT_VERSION_V2, INSTRUCTION_V2, OUTPUT_SCHEMA_V2,
    OPTIONS_CURRICULUM_SINGLE, OPTIONS_CURRICULUM_BATCH,
    JD_IDS, single_schema_v2, batch_schema_v2,
)

BATCH_NOTE = (
    '\n다른 JD와 상대평가하지 말고 각 JD를 독립 평가하세요. '
    '입력 순서대로 모든 JD를 한 번씩 평가하고 {"results": [각 JD 결과]}로 반환하세요.'
)


def check_one(jd, result):
    """JD 한 건의 형식·규칙 검증. 응답은 고치지 않고 판정만 돌려줍니다."""
    checks = {"format_valid": False, "rules_valid": False, "errors": []}
    if not isinstance(result, dict) or set(result) != set(OUTPUT_SCHEMA["required"]):
        checks["errors"].append("필수 필드가 누락되었거나 지정하지 않은 필드가 있습니다.")
        return checks
    scores = {key: result[key] for key in ("AX", "DS", "LLM", "PA")}
    if any(type(score) is not int or not 0 <= score <= 100 for score in scores.values()):
        checks["errors"].append("점수는 0~100 정수여야 합니다.")
        return checks
    if not isinstance(result["jd_id"], str) or type(result["none"]) is not bool:
        checks["errors"].append("jd_id 또는 none 타입이 올바르지 않습니다.")
        return checks
    if result["top1"] not in ("AX", "DS", "LLM", "PA", "NONE"):
        checks["errors"].append("top1 값이 올바르지 않습니다.")
        return checks
    skills = result["evidence_skills"]
    if not isinstance(skills, list) or not all(
        isinstance(skill, str) and skill.strip() for skill in skills
    ):
        checks["errors"].append("evidence_skills 형식이 올바르지 않습니다.")
        return checks
    if len(skills) > 3:
        checks["errors"].append(f"evidence_skills는 최대 3개여야 합니다(실제 {len(skills)}개).")
        return checks
    if not isinstance(result["reason"], str) or not result["reason"].strip():
        checks["errors"].append("reason 형식이 올바르지 않습니다.")
        return checks
    checks["format_valid"] = True

    errors = []
    if result["jd_id"] != jd["jd_id"]:
        errors.append(f'jd_id 불일치(기대 {jd["jd_id"]}, 응답 {result["jd_id"]}).')
    is_none = max(scores.values()) <= 40
    if result["none"] != is_none:
        errors.append(f"none 값이 점수 기준과 일치하지 않습니다(기대 {is_none}).")
    if is_none:
        if result["top1"] != "NONE":
            errors.append("모든 점수가 40 이하이면 top1은 NONE이어야 합니다.")
    elif scores.get(result["top1"]) != max(scores.values()):
        errors.append("top1이 최고점 직무와 일치하지 않습니다.")
    checks["rules_valid"] = not errors
    checks["errors"] = errors
    return checks


def call_model(client, model, jd, cycle, result_file, curriculum=None):
    # Batch도 이전 호출 이력 없이 새 메시지 하나로 전달합니다.
    # curriculum이 주어지면 3단계(v4) 설정으로 동작하고, None이면 기존 1·2단계 그대로입니다.
    is_batch = isinstance(jd, list)
    jds = jd if is_batch else [jd]
    inputs = [{"jd_id": item["jd_id"], "jd_text": item["jd_text"]} for item in jds]
    use_v2 = curriculum is not None
    if use_v2:
        instruction = INSTRUCTION_V2
        version = PROMPT_VERSION_V2
        options = OPTIONS_CURRICULUM_BATCH if is_batch else OPTIONS_CURRICULUM_SINGLE
        schema = batch_schema_v2(len(jds)) if is_batch else single_schema_v2(jds[0]["jd_id"])
    else:
        instruction = INSTRUCTION
        version = PROMPT_VERSION
        options = OPTIONS
        schema = OUTPUT_SCHEMA
    if is_batch:
        instruction = instruction.replace("다음 JD 하나에 대해", "다음 JD 각각에 대해") + BATCH_NOTE
        if not use_v2:
            schema = {"type": "object", "properties": {"results": {
                "type": "array", "items": OUTPUT_SCHEMA, "minItems": len(jds), "maxItems": len(jds)}},
                "required": ["results"], "additionalProperties": False}
    payload = json.dumps(inputs if is_batch else inputs[0], ensure_ascii=False)
    if use_v2:
        # 공통 평가 지시 + <CURRICULUM_CONTEXT> + 평가할 JD 순서로 조립합니다.
        prompt = (instruction + "\n\n<CURRICULUM_CONTEXT>\n" + curriculum
                  + "\n</CURRICULUM_CONTEXT>\n\n" + payload)
    else:
        prompt = instruction + "\n\n" + payload
    record_id = [item["jd_id"] for item in jds] if is_batch else jd["jd_id"]
    record = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "model": model, "evaluation_type": "batch" if is_batch else "single",
        "condition": "curriculum" if use_v2 else "jd_only", "cycle": cycle,
        "jd_id": record_id, "prompt_version": version + ("-batch" if is_batch else ""),
        "options": options, "output_schema": schema, "prompt": prompt,
        "curriculum_sha256": (hashlib.sha256(curriculum.encode("utf-8")).hexdigest()
                              if use_v2 else None),
        "curriculum_chars": len(curriculum) if use_v2 else None,
        "success": False, "call_success": False, "format_valid": None,
        "rules_valid": None, "per_jd_rules": None,
        "error": None, "raw_response": "", "parsed_result": None,
        "elapsed_seconds": None, "prompt_eval_count": None, "eval_count": None,
        "eval_duration": None, "load_duration": None, "done_reason": None,
        "tokens_per_second": None, "evidence_in_jd": None,
    }
    start = perf_counter()
    stage = "model_call"
    try:
        # 매번 새 메시지 목록: 이전 JD·답변·사이클의 대화 이력을 넣지 않습니다.
        response = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=False, format=schema, options=options, keep_alive="30m",
            think=False,
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

        # JD별로 검증 결과를 기록합니다. 첫 위반에서 중단하지 않습니다.
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
            # JD01~JD10이 정확히 한 번씩 있는지 확인합니다.
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
    except Exception as error:
        record["error"] = f"{stage}: {type(error).__name__}: {error}"
    if record["elapsed_seconds"] is None:
        record["elapsed_seconds"] = round(perf_counter() - start, 4)

    with result_file.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"{model} | cycle={cycle} | {record_id} | "
          f"call={record['call_success']} | format={record['format_valid']} | "
          f"rules={record['rules_valid']} | success={record['success']}")
    if record["error"]:
        print(f"  오류: {record['error']}")


def run_single_evaluation(client, model, dataset, result_file, curriculum=None):
    for cycle in range(1, CYCLE_COUNT + 1):
        for jd in dataset:
            call_model(client, model, jd, cycle, result_file, curriculum)


def run_batch_evaluation(client, model, dataset, result_file, curriculum=None):
    for cycle in range(1, CYCLE_COUNT + 1):
        call_model(client, model, dataset, cycle, result_file, curriculum)


def warmup(client, model, options):
    """본 실험 전 1회. 결과는 저장하지 않습니다."""
    try:
        client.chat(
            model=model,
            messages=[{"role": "user", "content": 'JSON으로 {"ready":true}를 출력하세요.'}],
            stream=False, format="json", options=options, keep_alive="30m", think=False,
        )
        print(f"워밍업 완료: {model}")
    except Exception as error:
        print(f"워밍업 실패: {model}: {error}. 본 호출의 실패도 각각 기록합니다.")


def unload(client, model):
    try:
        client.generate(model=model, keep_alive=0)
    except Exception as error:
        print(f"모델 해제 실패: {error}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", action="store_true", help="Single 대신 Batch만 실행")
    parser.add_argument("--single", action="store_true", help="Single 실행(기본 동작과 동일)")
    parser.add_argument("--curriculum", action="store_true", help="3단계 Curriculum 조건으로 실행")
    parser.add_argument("--stage3", action="store_true",
                        help="Curriculum Single 40회 후 Curriculum Batch 4회를 연속 실행")
    args = parser.parse_args()
    with DATA_FILE.open(encoding="utf-8") as file:
        dataset = json.load(file)
    if [jd["jd_id"] for jd in dataset] != [f"JD{i:02d}" for i in range(1, 11)]:
        raise ValueError("데이터는 JD01~JD10 순서의 10개여야 합니다.")
    if any(not isinstance(jd["jd_text"], str) or not jd["jd_text"].strip() for jd in dataset):
        raise ValueError("JD 원문이 비어 있습니다.")

    use_curriculum = args.curriculum or args.stage3
    curriculum = None
    if use_curriculum:
        curriculum = CURRICULUM_FILE.read_text(encoding="utf-8")
        if not curriculum.strip():
            raise ValueError("curriculum_context.md가 비어 있습니다.")
        # reference.json은 이 파일에서 import하지 않습니다. 오염 여부를 한 번 더 확인합니다.
        if "reference_label" in curriculum or "reference_scores" in curriculum:
            raise ValueError("커리큘럼에 reference 값이 섞여 있습니다.")

    client = Client(host="http://127.0.0.1:11434", timeout=TIMEOUT)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d_%H%M%S_%f}"

    if args.stage3:
        single_file = RESULTS_DIR / f"stage3-curriculum-single-v2_{stamp}.jsonl"
        batch_file = RESULTS_DIR / f"stage3-curriculum-batch-v2_{stamp}.jsonl"
        print(f"Single 결과: {single_file}")
        print(f"Batch  결과: {batch_file}")
        print(f"예정 호출 수: Single {len(MODELS) * len(dataset) * CYCLE_COUNT}회 + "
              f"Batch {len(MODELS) * CYCLE_COUNT}회")
        for model in MODELS:
            warmup(client, model, OPTIONS_CURRICULUM_SINGLE)
            run_single_evaluation(client, model, dataset, single_file, curriculum)
            unload(client, model)
        for model in MODELS:
            warmup(client, model, OPTIONS_CURRICULUM_BATCH)
            run_batch_evaluation(client, model, dataset, batch_file, curriculum)
            unload(client, model)
        print(f"실행 종료: {single_file} / {batch_file}")
    else:
        prefix = PROMPT_VERSION_V2 if use_curriculum else PROMPT_VERSION
        mode = "batch" if args.batch else "single"
        result_file = RESULTS_DIR / f"{prefix}_{mode}_{stamp}.jsonl"
        options = (OPTIONS_CURRICULUM_BATCH if args.batch else OPTIONS_CURRICULUM_SINGLE) \
            if use_curriculum else OPTIONS
        print(f"결과 저장 위치: {result_file}")
        for model in MODELS:
            warmup(client, model, options)
            if args.batch:
                run_batch_evaluation(client, model, dataset, result_file, curriculum)
            else:
                run_single_evaluation(client, model, dataset, result_file, curriculum)
            unload(client, model)
        print(f"실행 종료: {result_file}")
