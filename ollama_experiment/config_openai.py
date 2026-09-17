"""gpt-5.6-luna 비교 실험 설정 (외부 OpenAI API).

로컬 실험의 프롬프트·스키마를 config.py에서 import해 그대로 재사용한다.
- 1·2단계(JD-only)  : INSTRUCTION + OUTPUT_SCHEMA        (로컬 1·2단계와 동일)
- 3단계(Curriculum) : INSTRUCTION_V2 + *_schema_v2       (로컬 3단계 v2와 동일)
기존 파일은 일절 수정하지 않는다.
"""

import sys

sys.dont_write_bytecode = True

import copy  # noqa: E402

from config import (  # noqa: E402
    CURRICULUM_FILE, DATA_FILE, INSTRUCTION, INSTRUCTION_V2, JD_IDS,
    OUTPUT_SCHEMA, OUTPUT_SCHEMA_V2, RESULTS_DIR,
    batch_schema_v2, single_schema_v2,
)

MODEL = "gpt-5.6-luna"
CYCLE_COUNT = 2

# Chat Completions 요청 파라미터.
# temperature / top_p / top_k / repeat_penalty 는 이 모델이 지원하지 않아 전송하지 않는다.
REQUEST_PARAMS = {
    "seed": 42,
    "reasoning_effort": "medium",
    # 로컬 num_predict 는 "보이는 출력"만 제한했으나 OpenAI 상한은 reasoning 토큰을
    # 포함한다. 동등 이상의 가시 출력 예산을 주기 위해 16384로 둔다.
    "max_completion_tokens": 16384,
}

BATCH_NOTE = (
    '\n다른 JD와 상대평가하지 말고 각 JD를 독립 평가하세요. '
    '입력 순서대로 모든 JD를 한 번씩 평가하고 {"results": [각 JD 결과]}로 반환하세요.'
)

# Structured Outputs strict 모드가 거부하는 제약 키워드.
# const / enum / required / additionalProperties 는 유지되므로 jd_id 보호는 그대로다.
STRICT_UNSUPPORTED = (
    "minimum", "maximum", "multipleOf",
    "minLength", "maxLength", "pattern", "format",
    "minItems", "maxItems", "uniqueItems",
    "minProperties", "maxProperties",
)


def batch_schema_v1(count):
    """로컬 1·2단계와 동일한 Batch 스키마."""
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": OUTPUT_SCHEMA,
                "minItems": count,
                "maxItems": count,
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }


def strip_for_strict(node, removed):
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in STRICT_UNSUPPORTED:
                removed.append(key)
                continue
            out[key] = strip_for_strict(value, removed)
        return out
    if isinstance(node, list):
        return [strip_for_strict(item, removed) for item in node]
    return node


def response_format(schema, strict=True):
    """response_format 페이로드와 제거된 키워드 목록."""
    removed = []
    payload = strip_for_strict(copy.deepcopy(schema), removed) if strict else copy.deepcopy(schema)
    return (
        {
            "type": "json_schema",
            "json_schema": {
                "name": "jd_fit_assessment",
                "schema": payload,
                "strict": strict,
            },
        },
        sorted(set(removed)),
    )


def build(condition, is_batch, jds):
    """(instruction, schema, prompt_version) 을 조건별로 돌려준다."""
    count = len(jds)
    if condition == "curriculum":
        instruction = INSTRUCTION_V2
        schema = batch_schema_v2(count) if is_batch else single_schema_v2(jds[0]["jd_id"])
        version = "gpt56luna-curriculum"
    else:
        instruction = INSTRUCTION
        schema = batch_schema_v1(count) if is_batch else copy.deepcopy(OUTPUT_SCHEMA)
        version = "gpt56luna-jdonly"
    if is_batch:
        instruction = instruction.replace("다음 JD 하나에 대해", "다음 JD 각각에 대해") + BATCH_NOTE
        version += "-batch"
    return instruction, schema, version


__all__ = [
    "DATA_FILE", "RESULTS_DIR", "CURRICULUM_FILE", "JD_IDS",
    "OUTPUT_SCHEMA", "OUTPUT_SCHEMA_V2",
    "MODEL", "CYCLE_COUNT", "REQUEST_PARAMS",
    "build", "response_format",
]
