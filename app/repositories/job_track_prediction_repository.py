from app.db import get_conn

# 교육 트랙 <-> curriculum_code 매핑 (curriculum 테이블 기준)
TRACK_TO_CURRICULUM = {
    "AX": "CUR001",   # AX Engineer
    "DS": "CUR002",   # Data Scientist
    "LLM": "CUR003",  # LLM Engineer
    "PA": "CUR004",   # Physical AI
}

DDL = """
CREATE TABLE IF NOT EXISTS job_track_prediction (
    prediction_id       BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_posting_id      BIGINT       NOT NULL,
    snapshot_id         BIGINT       NOT NULL,
    ax_score            SMALLINT     NULL,
    ds_score            SMALLINT     NULL,
    llm_score           SMALLINT     NULL,
    pa_score            SMALLINT     NULL,
    top1_track          VARCHAR(10)  NULL,
    top1_curriculum_code VARCHAR(20) NULL,
    none_flag           TINYINT(1)   NULL,
    evidence_skills     JSON         NULL,
    reason              TEXT         NULL,
    model_name          VARCHAR(100) NOT NULL,
    inference_mode      VARCHAR(20)  NOT NULL,
    prompt_version      VARCHAR(50)  NOT NULL,
    options_json        JSON         NULL,
    curriculum_sha256   VARCHAR(64)  NULL,
    success             TINYINT(1)   NOT NULL DEFAULT 0,
    validation_status   VARCHAR(30)  NOT NULL DEFAULT 'UNKNOWN',
    error_message       TEXT         NULL,
    raw_response        LONGTEXT     NULL,
    prompt_eval_count   INT          NULL,
    eval_count          INT          NULL,
    elapsed_seconds     DECIMAL(10,4) NULL,
    predicted_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_job_track_prediction
        (job_posting_id, model_name, prompt_version, inference_mode),
    KEY idx_jtp_top1 (top1_track),
    KEY idx_jtp_curriculum (top1_curriculum_code),
    CONSTRAINT fk_jtp_job FOREIGN KEY (job_posting_id)
        REFERENCES job_posting (job_posting_id),
    CONSTRAINT fk_jtp_snapshot FOREIGN KEY (snapshot_id)
        REFERENCES job_posting_snapshot (snapshot_id),
    CONSTRAINT fk_jtp_curriculum FOREIGN KEY (top1_curriculum_code)
        REFERENCES curriculum (curriculum_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

UPSERT = """
INSERT INTO job_track_prediction (
    job_posting_id, snapshot_id,
    ax_score, ds_score, llm_score, pa_score,
    top1_track, top1_curriculum_code, none_flag,
    evidence_skills, reason,
    model_name, inference_mode, prompt_version,
    options_json, curriculum_sha256,
    success, validation_status, error_message, raw_response,
    prompt_eval_count, eval_count, elapsed_seconds, predicted_at
) VALUES (
    %(job_posting_id)s, %(snapshot_id)s,
    %(ax_score)s, %(ds_score)s, %(llm_score)s, %(pa_score)s,
    %(top1_track)s, %(top1_curriculum_code)s, %(none_flag)s,
    %(evidence_skills)s, %(reason)s,
    %(model_name)s, %(inference_mode)s, %(prompt_version)s,
    %(options_json)s, %(curriculum_sha256)s,
    %(success)s, %(validation_status)s, %(error_message)s, %(raw_response)s,
    %(prompt_eval_count)s, %(eval_count)s, %(elapsed_seconds)s, NOW()
)
ON DUPLICATE KEY UPDATE
    snapshot_id = VALUES(snapshot_id),
    ax_score = VALUES(ax_score),
    ds_score = VALUES(ds_score),
    llm_score = VALUES(llm_score),
    pa_score = VALUES(pa_score),
    top1_track = VALUES(top1_track),
    top1_curriculum_code = VALUES(top1_curriculum_code),
    none_flag = VALUES(none_flag),
    evidence_skills = VALUES(evidence_skills),
    reason = VALUES(reason),
    options_json = VALUES(options_json),
    curriculum_sha256 = VALUES(curriculum_sha256),
    success = VALUES(success),
    validation_status = VALUES(validation_status),
    error_message = VALUES(error_message),
    raw_response = VALUES(raw_response),
    prompt_eval_count = VALUES(prompt_eval_count),
    eval_count = VALUES(eval_count),
    elapsed_seconds = VALUES(elapsed_seconds),
    predicted_at = NOW()
"""


def ensure_table():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(DDL)
    finally:
        cur.close()
        conn.close()


def find_target_jobs(limit=None):
    """현재 스냅샷(is_current=1)의 JD 원문을 job_posting_id 순으로 돌려준다."""
    sql = """
    SELECT
        jp.job_posting_id,
        jp.job_title,
        js.snapshot_id,
        js.raw_jd_text
    FROM job_posting jp
    JOIN job_posting_snapshot js
      ON js.job_posting_id = jp.job_posting_id
     AND js.is_current = 1
    ORDER BY jp.job_posting_id
    """
    params = []
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def find_existing_keys(model_name, prompt_version, inference_mode):
    """이미 같은 조건으로 성공 저장된 job_posting_id 집합."""
    sql = """
    SELECT job_posting_id
    FROM job_track_prediction
    WHERE model_name = %s AND prompt_version = %s AND inference_mode = %s
      AND success = 1
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql, (model_name, prompt_version, inference_mode))
        return {row[0] for row in cur.fetchall()}
    finally:
        cur.close()
        conn.close()


def upsert_prediction(row):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(UPSERT, row)
        return cur.rowcount
    finally:
        cur.close()
        conn.close()


def find_predictions(limit=5, model_name=None, prompt_version=None):
    sql = """
    SELECT
        p.prediction_id,
        p.job_posting_id,
        jp.job_title,
        p.ax_score, p.ds_score, p.llm_score, p.pa_score,
        p.top1_track, p.top1_curriculum_code, p.none_flag,
        p.evidence_skills, p.reason,
        p.model_name, p.inference_mode, p.prompt_version,
        p.success, p.validation_status, p.predicted_at
    FROM job_track_prediction p
    JOIN job_posting jp ON jp.job_posting_id = p.job_posting_id
    WHERE 1 = 1
    """
    params = []
    if model_name:
        sql += " AND p.model_name = %s"
        params.append(model_name)
    if prompt_version:
        sql += " AND p.prompt_version = %s"
        params.append(prompt_version)
    sql += " ORDER BY p.job_posting_id LIMIT %s"
    params.append(limit)

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def summarize(model_name, prompt_version, inference_mode):
    sql = """
    SELECT
        COUNT(*) AS total,
        SUM(success = 1) AS success_count,
        SUM(success = 0) AS failure_count,
        SUM(none_flag = 1) AS none_count
    FROM job_track_prediction
    WHERE model_name = %s AND prompt_version = %s AND inference_mode = %s
    """
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, (model_name, prompt_version, inference_mode))
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def track_distribution(model_name, prompt_version, inference_mode):
    sql = """
    SELECT top1_track, COUNT(*) AS n
    FROM job_track_prediction
    WHERE model_name = %s AND prompt_version = %s AND inference_mode = %s
      AND success = 1
    GROUP BY top1_track
    ORDER BY n DESC
    """
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, (model_name, prompt_version, inference_mode))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()
