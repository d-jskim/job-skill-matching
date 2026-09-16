from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()
APP_DIR = Path(__file__).resolve().parents[1]


@router.get("/", response_class=HTMLResponse)
def home():
    page = APP_DIR / "templates" / "job_skill_graph.html"
    return page.read_text(encoding="utf-8")
