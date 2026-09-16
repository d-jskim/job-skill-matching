from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.services.graph_service import build_curriculum_graph

router = APIRouter(prefix="/api", tags=["graph"])


@router.get("/graph")
def graph(
    curriculum_code: str = Query("CUR003"),
    days: int = Query(settings.default_job_days, ge=0, le=3650),
):
    try:
        return build_curriculum_graph(curriculum_code, days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
