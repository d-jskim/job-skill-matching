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
