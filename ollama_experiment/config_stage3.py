"""3단계 Curriculum Context 실험 설정.

1·2단계 코드(config.py, experiment.py)는 수정하지 않는다.
공통 평가 지시와 출력 스키마는 config.py에서 그대로 가져와 1·2단계와의
프롬프트 동일성을 보장한다.
"""

import sys

sys.dont_write_bytecode = True  # 기존 __pycache__를 건드리지 않는다.

from pathlib import Path

from config import (  # noqa: E402  (1·2단계 원문을 그대로 재사용)
    DATA_FILE,
    INSTRUCTION,
    MODELS,
    OUTPUT_SCHEMA,
    RESULTS_DIR,
)

BASE_DIR = Path(__file__).resolve().parent
CURRICULUM_FILE = BASE_DIR / "data" / "curriculum_context.md"

CONDITION = "curriculum"
PROMPT_VERSION = "stage3-curriculum"
CYCLE_COUNT = 2

# 클라이언트 타임아웃만 상향한다. 실험 조건이 아니라 실패 방지용 가드다.
TIMEOUT = 900

# 44회 호출 전부 동일하게 적용한다.
OPTIONS = {
    "num_ctx": 24576,
    "temperature": 0,
    "seed": 42,
    "top_p": 1.0,
    "top_k": 0,
    "repeat_penalty": 1.0,
    "num_predict": 8192,
}

# Batch 지시문은 experiment.py와 완전히 동일한 방식으로 파생시킨다.
BATCH_ADDENDUM = (
    '\n다른 JD와 상대평가하지 말고 각 JD를 독립 평가하세요. '
    '입력 순서대로 모든 JD를 한 번씩 평가하고 {"results": [각 JD 결과]}로 반환하세요.'
)

# 프롬프트에 Reference가 새어 들어갔는지 검사할 금칙어.
# reference.json은 이 실험에서 import조차 하지 않는다.
REFERENCE_FORBIDDEN = ("reference_label", "reference_scores", "reference")


def batch_instruction() -> str:
    """experiment.py의 Batch 지시문 생성 로직과 동일."""
    return INSTRUCTION.replace("다음 JD 하나에 대해", "다음 JD 각각에 대해") + BATCH_ADDENDUM


def batch_schema(count: int) -> dict:
    """experiment.py의 Batch 스키마 생성 로직과 동일."""
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


def build_prompt(instruction: str, curriculum: str, payload_json: str) -> str:
    """공통 평가 지시 + <CURRICULUM_CONTEXT> + 평가할 JD 순서로 조립한다."""
    return (
        instruction
        + "\n\n<CURRICULUM_CONTEXT>\n"
        + curriculum
        + "\n</CURRICULUM_CONTEXT>\n\n"
        + payload_json
    )


__all__ = [
    "DATA_FILE", "RESULTS_DIR", "MODELS", "INSTRUCTION", "OUTPUT_SCHEMA",
    "CURRICULUM_FILE", "CONDITION", "PROMPT_VERSION", "CYCLE_COUNT",
    "TIMEOUT", "OPTIONS", "REFERENCE_FORBIDDEN",
    "batch_instruction", "batch_schema", "build_prompt",
]
