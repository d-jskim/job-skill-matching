from fastapi import APIRouter, Query

from app.config import settings
from app.services.job_service import get_jobs_for_skill

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/by-skill/{skill_code}")
def jobs_by_skill(
    skill_code: str,
    days: int = Query(settings.default_job_days, ge=0, le=3650),
):
    return get_jobs_for_skill(skill_code, days)
