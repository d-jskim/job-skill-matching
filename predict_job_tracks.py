"""DB의 채용공고 전체에 대해 4개 교육 트랙(AX/DS/LLM/PA) 적합도를 예측해 저장한다.

확정 사항 (재비교하지 않음):
- 모델      : qwen3:4b-instruct-2507-q4_K_M
- 추론 방식 : Single independent inference (JD 1건 = 새 요청 1회, 대화 이력 없음)
- 프롬프트  : ollama_experiment 의 검증된 Curriculum Single 설정(v4-curriculum-strict)

실행:
    uv run --no-project --with ollama python predict_job_tracks.py --limit 3   # 테스트
    uv run --no-project --with ollama python predict_job_tracks.py            # 전체
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter

BASE_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = BASE_DIR / "ollama_experiment"
sys.path.insert(0, str(EXPERIMENT_DIR))

from ollama import Client  # noqa: E402

# 검증된 실험 설정을 그대로 재사용한다 (새 프롬프트를 만들지 않는다).
from config import (  # noqa: E402
    CURRICULUM_FILE, INSTRUCTION_V2, OPTIONS_CURRICULUM_SINGLE,
    PROMPT_VERSION_V2, single_schema_v2,
)
from experiment import check_one  # noqa: E402

from app.repositories import job_track_prediction_repository as repo  # noqa: E402

MODEL_NAME = "qwen3:4b-instruct-2507-q4_K_M"
INFERENCE_MODE = "single"
TIMEOUT = 180


def predict_one(client, job, curriculum, curriculum_sha):
    """JD 1건을 독립 호출한다. 이전 호출의 messages/response를 전달하지 않는다."""
    jd_id = f"JD{int(job['job_posting_id']):02d}"
    schema = single_schema_v2(jd_id)
    payload = json.dumps({"jd_id": jd_id, "jd_text": job["raw_jd_text"]}, ensure_ascii=False)
    prompt = (INSTRUCTION_V2 + "\n\n<CURRICULUM_CONTEXT>\n" + curriculum
              + "\n</CURRICULUM_CONTEXT>\n\n" + payload)

    row = {
        "job_posting_id": job["job_posting_id"],
        "snapshot_id": job["snapshot_id"],
        "ax_score": None, "ds_score": None, "llm_score": None, "pa_score": None,
        "top1_track": None, "top1_curriculum_code": None, "none_flag": None,
        "evidence_skills": None, "reason": None,
        "model_name": MODEL_NAME,
        "inference_mode": INFERENCE_MODE,
        "prompt_version": PROMPT_VERSION_V2,
        "options_json": json.dumps(OPTIONS_CURRICULUM_SINGLE, ensure_ascii=False),
        "curriculum_sha256": curriculum_sha,
        "success": 0, "validation_status": "UNKNOWN",
        "error_message": None, "raw_response": None,
        "prompt_eval_count": None, "eval_count": None, "elapsed_seconds": None,
    }

    start = perf_counter()
    stage = "model_call"
    try:
        # 매 호출마다 새로운 messages 배열 1개만 전달한다.
        response = client.chat(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            format=schema,
            options=OPTIONS_CURRICULUM_SINGLE,
            keep_alive="30m",
            think=False,
        )
        row["elapsed_seconds"] = round(perf_counter() - start, 4)
        row["raw_response"] = response.message.content or ""
        row["prompt_eval_count"] = getattr(response, "prompt_eval_count", None)
        row["eval_count"] = getattr(response, "eval_count", None)
        if getattr(response, "done_reason", None) == "length":
            raise ValueError("출력 토큰 한도에 도달했습니다.")

        stage = "json_parse"
        result = json.loads(row["raw_response"])

        stage = "validation"
        checks = check_one({"jd_id": jd_id, "jd_text": job["raw_jd_text"]}, result)
        if not checks["format_valid"]:
            row["validation_status"] = "FORMAT_INVALID"
            raise ValueError("; ".join(checks["errors"]) or "형식 검증 실패")
        if not checks["rules_valid"]:
            row["validation_status"] = "RULES_INVALID"
            raise ValueError("; ".join(checks["errors"]) or "규칙 검증 실패")

        row.update({
            "ax_score": result["AX"], "ds_score": result["DS"],
            "llm_score": result["LLM"], "pa_score": result["PA"],
            "top1_track": result["top1"],
            "top1_curriculum_code": repo.TRACK_TO_CURRICULUM.get(result["top1"]),
            "none_flag": 1 if result["none"] else 0,
            "evidence_skills": json.dumps(result["evidence_skills"], ensure_ascii=False),
            "reason": result["reason"],
            "success": 1, "validation_status": "VALID",
        })
    except Exception as error:  # noqa: BLE001
        if row["validation_status"] == "UNKNOWN":
            row["validation_status"] = stage.upper() + "_FAILED"
        row["error_message"] = f"{stage}: {type(error).__name__}: {error}"
    if row["elapsed_seconds"] is None:
        row["elapsed_seconds"] = round(perf_counter() - start, 4)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="처리할 JD 수(테스트용)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="같은 조건으로 이미 성공 저장된 JD는 건너뜀")
    args = parser.parse_args()

    curriculum = CURRICULUM_FILE.read_text(encoding="utf-8")
    curriculum_sha = hashlib.sha256(curriculum.encode("utf-8")).hexdigest()

    repo.ensure_table()
    jobs = repo.find_target_jobs(args.limit)
    skip = repo.find_existing_keys(MODEL_NAME, PROMPT_VERSION_V2, INFERENCE_MODE) \
        if args.skip_existing else set()

    print("=" * 84)
    print(f"모델 {MODEL_NAME} / mode={INFERENCE_MODE} / prompt_version={PROMPT_VERSION_V2}")
    print(f"옵션 {json.dumps(OPTIONS_CURRICULUM_SINGLE)}")
    print(f"커리큘럼 {len(curriculum)}자 sha256={curriculum_sha[:16]}")
    print(f"대상 JD {len(jobs)}건" + (f" (기존 성공 {len(skip)}건 건너뜀)" if skip else ""))
    print("=" * 84, flush=True)

    client = Client(host="http://127.0.0.1:11434", timeout=TIMEOUT)
    ok = fail = saved = skipped = 0
    failures = []

    for job in jobs:
        if job["job_posting_id"] in skip:
            skipped += 1
            continue
        row = predict_one(client, job, curriculum, curriculum_sha)
        repo.upsert_prediction(row)
        saved += 1
        if row["success"]:
            ok += 1
            print(f"  OK   job_id={row['job_posting_id']:>3} "
                  f"AX={row['ax_score']:>3} DS={row['ds_score']:>3} "
                  f"LLM={row['llm_score']:>3} PA={row['pa_score']:>3} "
                  f"top1={row['top1_track']:<4} none={row['none_flag']} "
                  f"{row['elapsed_seconds']}s", flush=True)
        else:
            fail += 1
            failures.append((row["job_posting_id"], row["validation_status"],
                             row["error_message"]))
            print(f"  FAIL job_id={row['job_posting_id']:>3} "
                  f"status={row['validation_status']} | {row['error_message'][:200]}",
                  flush=True)

    try:
        client.generate(model=MODEL_NAME, keep_alive=0)
    except Exception as error:  # noqa: BLE001
        print(f"모델 해제 실패: {error}")

    print("\n" + "=" * 84)
    print(f"대상 {len(jobs)}건 / 처리 {saved}건 / 성공 {ok}건 / 실패 {fail}건 / 건너뜀 {skipped}건")
    if failures:
        print("실패 목록 (job_posting_id | 실패단계 | 오류):")
        for job_id, status, message in failures:
            print(f"  {job_id} | {status} | {message[:160]}")
    print(f"DB 집계: {repo.summarize(MODEL_NAME, PROMPT_VERSION_V2, INFERENCE_MODE)}")
    print(f"top1 분포: {repo.track_distribution(MODEL_NAME, PROMPT_VERSION_V2, INFERENCE_MODE)}")
    print("=" * 84, flush=True)


if __name__ == "__main__":
    main()
