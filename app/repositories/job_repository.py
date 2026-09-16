from app.db import get_conn


def find_jobs_by_skill(skill_code: str, cutoff, limit: int = 20):
    cutoff_clause = ""
    params = [skill_code]

    if cutoff is not None:
        cutoff_clause = "AND js.captured_at >= %s"
        params.append(cutoff)

    params.append(limit)

    sql = f"""
    SELECT
        jp.job_posting_id,
        c.company_name,
        jp.job_title,
        jp.posting_url,
        jp.published_at,
        jp.collected_at,
        js.captured_at,
        GROUP_CONCAT(
            DISTINCT s2.canonical_name
            ORDER BY s2.canonical_name
            SEPARATOR ', '
        ) AS matched_skills
    FROM job_skill_mention jsm
    JOIN job_posting_section sec
      ON sec.section_id = jsm.section_id
    JOIN job_posting_snapshot js
      ON js.snapshot_id = sec.snapshot_id
    JOIN job_posting jp
      ON jp.job_posting_id = js.job_posting_id
    JOIN company c
      ON c.company_code = jp.company_code
    LEFT JOIN job_posting_section sec2
      ON sec2.snapshot_id = js.snapshot_id
    LEFT JOIN job_skill_mention jsm2
      ON jsm2.section_id = sec2.section_id
    LEFT JOIN skill s2
      ON s2.skill_code = jsm2.skill_code
    WHERE jsm.skill_code = %s
      AND js.is_current = 1
      {cutoff_clause}
    GROUP BY
        jp.job_posting_id,
        c.company_name,
        jp.job_title,
        jp.posting_url,
        jp.published_at,
        jp.collected_at,
        js.captured_at
    ORDER BY
        COALESCE(jp.published_at, js.captured_at, jp.collected_at) DESC
    LIMIT %s
    """

    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()
