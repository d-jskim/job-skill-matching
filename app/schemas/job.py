from pydantic import BaseModel


class JobResponse(BaseModel):
    job_posting_id: int
    company_name: str
    job_title: str
    posting_url: str | None = None
    published_at: str | None = None
    collected_at: str | None = None
    captured_at: str | None = None
    matched_skills: str = ""

    # 최신 서비스용 LLM 직무 예측 결과.
    # success=1 결과가 없으면 모두 None으로 내려가고 UI는 중립색으로 표시한다.
    ax_score: int | None = None
    ds_score: int | None = None
    llm_score: int | None = None
    pa_score: int | None = None
    top1_track: str | None = None
    none_flag: bool | None = None
