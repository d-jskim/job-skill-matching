import json
import argparse
from datetime import datetime
from time import perf_counter

from ollama import Client
from config import (
    DATA_FILE, RESULTS_DIR, MODELS, TIMEOUT, CYCLE_COUNT,
    PROMPT_VERSION, OPTIONS, INSTRUCTION, OUTPUT_SCHEMA,
)


def call_model(client, model, jd, cycle, result_file):
    # Batch도 이전 호출 이력 없이 새 메시지 하나로 전달합니다.
    is_batch = isinstance(jd, list)
    jds = jd if is_batch else [jd]
    inputs = [{"jd_id": item["jd_id"], "jd_text": item["jd_text"]} for item in jds]
    instruction = INSTRUCTION
    schema = OUTPUT_SCHEMA
    if is_batch:
        instruction = instruction.replace("다음 JD 하나에 대해", "다음 JD 각각에 대해")
        instruction += '\n다른 JD와 상대평가하지 말고 각 JD를 독립 평가하세요. 입력 순서대로 모든 JD를 한 번씩 평가하고 {"results": [각 JD 결과]}로 반환하세요.'
        schema = {"type": "object", "properties": {"results": {
            "type": "array", "items": OUTPUT_SCHEMA, "minItems": len(jds), "maxItems": len(jds)}},
            "required": ["results"], "additionalProperties": False}
    prompt = instruction + "\n\n" + json.dumps(inputs if is_batch else inputs[0], ensure_ascii=False)
    record_id = [item["jd_id"] for item in jds] if is_batch else jd["jd_id"]
    record = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "model": model, "evaluation_type": "batch" if is_batch else "single", "cycle": cycle,
        "jd_id": record_id, "prompt_version": PROMPT_VERSION + ("-batch" if is_batch else ""),
        "options": OPTIONS, "output_schema": schema, "prompt": prompt,
        "success": False, "call_success": False, "format_valid": None,
        "rules_valid": None, "error": None, "raw_response": "", "parsed_result": None,
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

        record["format_valid"] = False
        stage = "json_parse"
        result = json.loads(record["raw_response"])
        record["parsed_result"] = result
        stage = "format_validation"
        if record["done_reason"] == "length":
            raise ValueError("출력 토큰 한도에 도달했습니다.")
        results = result["results"] if is_batch else [result]
        if not isinstance(results, list) or len(results) != len(jds):
            raise ValueError("JD 결과 개수가 일치하지 않습니다.")
        record["evidence_in_jd"] = {}
        for jd, result in zip(jds, results):
            if not isinstance(result, dict) or set(result) != set(OUTPUT_SCHEMA["required"]):
                raise ValueError("필수 필드가 누락되었거나 지정하지 않은 필드가 있습니다.")
            scores = {key: result[key] for key in ("AX", "DS", "LLM", "PA")}
            if any(type(score) is not int or not 0 <= score <= 100 for score in scores.values()):
                raise ValueError("점수는 0~100 정수여야 합니다.")
            if not isinstance(result["jd_id"], str) or type(result["none"]) is not bool:
                raise ValueError("jd_id 또는 none 타입이 올바르지 않습니다.")
            if not isinstance(result["top1"], str) or result["top1"] not in ("AX", "DS", "LLM", "PA", "NONE"):
                raise ValueError("top1 값이 올바르지 않습니다.")
            skills = result["evidence_skills"]
            if not isinstance(skills, list) or not all(
                isinstance(skill, str) and skill.strip() for skill in skills
            ) or not isinstance(result["reason"], str) or not result["reason"].strip():
                raise ValueError("근거 Skill 또는 판단 이유 형식이 올바르지 않습니다.")
            record["evidence_in_jd"][jd["jd_id"]] = {skill: skill in jd["jd_text"] for skill in skills}

            stage = "rule_validation"
            record["rules_valid"] = False
            if result["jd_id"] != jd["jd_id"]:
                raise ValueError("응답의 JD ID가 다릅니다.")
            is_none = max(scores.values()) <= 40
            if result["none"] != is_none:
                raise ValueError("none 값이 점수 기준과 일치하지 않습니다.")
            if is_none:
                if result["top1"] != "NONE":
                    raise ValueError("모든 점수가 40 이하이면 top1은 NONE이어야 합니다.")
            elif result["top1"] not in scores or scores[result["top1"]] != max(scores.values()):
                raise ValueError("top1이 최고점 직무와 일치하지 않습니다.")
        record["format_valid"] = True
        record["rules_valid"] = True
        record["success"] = True
    except Exception as error:
        if stage == "rule_validation":
            record["format_valid"] = True
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


def run_single_evaluation(client, model, dataset, result_file):
    for cycle in range(1, CYCLE_COUNT + 1):
        for jd in dataset:
            call_model(client, model, jd, cycle, result_file)


def run_batch_evaluation(client, model, dataset, result_file):
    for cycle in range(1, CYCLE_COUNT + 1):
        call_model(client, model, dataset, cycle, result_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", action="store_true", help="Single 대신 Batch 4회만 실행")
    args = parser.parse_args()
    with DATA_FILE.open(encoding="utf-8") as file:
        dataset = json.load(file)
    if [jd["jd_id"] for jd in dataset] != [f"JD{i:02d}" for i in range(1, 11)]:
        raise ValueError("데이터는 JD01~JD10 순서의 10개여야 합니다.")
    if any(not isinstance(jd["jd_text"], str) or not jd["jd_text"].strip() for jd in dataset):
        raise ValueError("JD 원문이 비어 있습니다.")

    client = Client(host="http://127.0.0.1:11434", timeout=TIMEOUT)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_file = RESULTS_DIR / f"{PROMPT_VERSION}_{'batch' if args.batch else 'single'}_{datetime.now():%Y%m%d_%H%M%S_%f}.jsonl"
    print(f"결과 저장 위치: {result_file}")
    for model in MODELS:
        try:
            client.chat(
                model=model,
                messages=[{"role": "user", "content": 'JSON으로 {"ready":true}를 출력하세요.'}],
                stream=False, format="json", options=OPTIONS, keep_alive="30m",
            )
            print(f"워밍업 완료: {model}")
        except Exception as error:
            print(f"워밍업 실패: {model}: {error}. 본 호출의 실패도 각각 기록합니다.")

        if args.batch:
            run_batch_evaluation(client, model, dataset, result_file)
        else:
            run_single_evaluation(client, model, dataset, result_file)

        try:
            client.generate(model=model, keep_alive=0)
        except Exception as error:
            print(f"모델 해제 실패: {error}. 메모리 상태 확인을 위해 종료합니다.")
            break
    print(f"실행 종료: {result_file}")
