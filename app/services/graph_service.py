from datetime import datetime, timedelta

from app.repositories.curriculum_repository import (
    find_curriculum,
    find_curriculum_skills_with_job_count,
)
from app.schemas.graph import GraphResponse


LLM_GROUPS = [
    ("rag", "RAG", {"SUB014"}),
    ("fine_tuning", "Fine-tuning", {"SUB013", "SUB065"}),
    ("agent", "Agent", {"SUB015"}),
    ("serving", "Serving", {"SUB017"}),
    ("llmops", "LLMOps", {"SUB062"}),
]

LLM_GROUP_BY_SUBCATEGORY = {
    category_code: (group_key, group_label)
    for group_key, group_label, category_codes in LLM_GROUPS
    for category_code in category_codes
}


def _cutoff(days: int):
    if days == 0:
        return None
    return datetime.now() - timedelta(days=days)


def _group_for_skill(curriculum_code: str, skill: dict):
    if curriculum_code == "CUR003":
        mapped = LLM_GROUP_BY_SUBCATEGORY.get(skill["category_code"])
        if mapped:
            return mapped
        return ("core_other", "Core / Other")

    # Other curricula remain DB-driven, but use the broad parent category
    # so the curriculum root has only a small number of direct children.
    group_key = skill["parent_category_code"] or "UNCATEGORIZED"
    group_label = skill["parent_category_name"] or "Other"
    return (group_key, group_label)


def build_curriculum_graph(curriculum_code: str, days: int) -> dict:
    curriculum = find_curriculum(curriculum_code)

    if curriculum is None:
        raise ValueError("존재하지 않는 교육과정입니다.")

    skills = find_curriculum_skills_with_job_count(
        curriculum_code=curriculum_code,
        cutoff=_cutoff(days),
    )

    root_id = f"curriculum_{curriculum_code}"

    elements = [{
        "data": {
            "id": root_id,
            "label": curriculum["curriculum_name"],
            "type": "root",
        }
    }]

    added_groups = set()

    for skill in skills:
        group_key, group_label = _group_for_skill(curriculum_code, skill)
        group_id = f"group_{curriculum_code}_{group_key}"

        if group_id not in added_groups:
            elements.append({
                "data": {
                    "id": group_id,
                    "label": group_label,
                    "type": "group",
                }
            })

            elements.append({
                "data": {
                    "id": f"edge_{root_id}_{group_id}",
                    "source": root_id,
                    "target": group_id,
                    "type": "curriculum_group",
                }
            })
            added_groups.add(group_id)

        skill_code = skill["skill_code"]
        job_count = int(skill["job_count"] or 0)

        elements.append({
            "data": {
                "id": skill_code,
                "skill_code": skill_code,
                "label": skill["display_name"],
                "canonical_name": skill["canonical_name"],
                "type": "skill",
                "job_count": job_count,
            }
        })

        elements.append({
            "data": {
                "id": f"edge_{group_id}_{skill_code}",
                "source": group_id,
                "target": skill_code,
                "type": "group_skill",
            }
        })

    return GraphResponse(
        curriculum_code=curriculum_code,
        curriculum_name=curriculum["curriculum_name"],
        days=days,
        elements=elements,
    ).model_dump()
