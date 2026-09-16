from datetime import datetime, timedelta

from app.repositories.job_repository import find_jobs_by_skill
from app.schemas.job import JobResponse


def _cutoff(days: int):
    if days == 0:
        return None
    return datetime.now() - timedelta(days=days)


def _to_text_datetime(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


def get_jobs_for_skill(skill_code: str, days: int) -> list[dict]:
    rows = find_jobs_by_skill(
        skill_code=skill_code,
        cutoff=_cutoff(days),
        limit=20,
    )

    result = []
    for row in rows:
        item = JobResponse(
            job_posting_id=row["job_posting_id"],
            company_name=row["company_name"],
            job_title=row["job_title"],
            posting_url=row.get("posting_url"),
            published_at=_to_text_datetime(row.get("published_at")),
            collected_at=_to_text_datetime(row.get("collected_at")),
            captured_at=_to_text_datetime(row.get("captured_at")),
            matched_skills=row.get("matched_skills") or "",
        )
        result.append(item.model_dump())

    return result
