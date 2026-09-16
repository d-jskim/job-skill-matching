from app.db import get_conn


def find_curriculum(curriculum_code: str):
    sql = """
    SELECT
        curriculum_code,
        curriculum_name,
        organization_name
    FROM curriculum
    WHERE curriculum_code = %s
    """

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(sql, (curriculum_code,))
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def find_curriculum_skills_with_job_count(curriculum_code: str, cutoff):
    cutoff_clause = ""
    params = [curriculum_code]

    if cutoff is not None:
        cutoff_clause = "AND js.captured_at >= %s"
        params.append(cutoff)

    sql = f"""
    SELECT
        curriculum_skill.skill_code,
        curriculum_skill.canonical_name,
        curriculum_skill.display_name,
        curriculum_skill.category_code,
        curriculum_skill.category_name,
        curriculum_skill.parent_category_code,
        curriculum_skill.parent_category_name,
        COALESCE(job_count.job_count, 0) AS job_count
    FROM (
        SELECT DISTINCT
            s.skill_code,
            s.canonical_name,
            COALESCE(sl.display_name, s.canonical_name) AS display_name,
            COALESCE(sc.category_code, 'UNCATEGORIZED') AS category_code,
            COALESCE(sc.category_name, 'Other') AS category_name,
            COALESCE(parent_sc.category_code, sc.category_code, 'UNCATEGORIZED') AS parent_category_code,
            COALESCE(parent_sc.category_name, sc.category_name, 'Other') AS parent_category_name
        FROM curriculum_version cv
        JOIN curriculum_module cm
          ON cm.curriculum_version_id = cv.curriculum_version_id
        JOIN curriculum_module_item cmi
          ON cmi.module_id = cm.module_id
        JOIN curriculum_item_skill cis
          ON cis.module_item_id = cmi.module_item_id
        JOIN skill s
          ON s.skill_code = cis.skill_code
        LEFT JOIN skill_localization sl
          ON sl.skill_code = s.skill_code
         AND sl.language_code = 'ko'
        LEFT JOIN skill_category_map scm
          ON scm.skill_code = s.skill_code
         AND scm.is_primary = 1
        LEFT JOIN skill_category sc
          ON sc.category_code = scm.category_code
        LEFT JOIN skill_category parent_sc
          ON parent_sc.category_code = sc.parent_category_code
        WHERE cv.curriculum_version_id = (
            SELECT cv2.curriculum_version_id
            FROM curriculum_version cv2
            WHERE cv2.curriculum_code = %s
              AND cv2.is_current = 1
            ORDER BY cv2.curriculum_version_id DESC
            LIMIT 1
        )
          AND s.is_active = 1
    ) curriculum_skill
    LEFT JOIN (
        SELECT
            jsm.skill_code,
            COUNT(DISTINCT jp.job_posting_id) AS job_count
        FROM job_skill_mention jsm
        JOIN job_posting_section sec
          ON sec.section_id = jsm.section_id
        JOIN job_posting_snapshot js
          ON js.snapshot_id = sec.snapshot_id
        JOIN job_posting jp
          ON jp.job_posting_id = js.job_posting_id
        WHERE js.is_current = 1
          {cutoff_clause}
        GROUP BY jsm.skill_code
    ) job_count
      ON job_count.skill_code = curriculum_skill.skill_code
    ORDER BY
        curriculum_skill.parent_category_name,
        curriculum_skill.category_name,
        curriculum_skill.canonical_name
    """

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()
