# Job Skill Matching

FastAPI + MySQL + Cytoscape.js 기반의 교육과정 Skill ↔ 채용공고 그래프 서비스입니다.

## Architecture
FastAPI 기반 Layered Architecture

- routes: HTTP 요청/응답
- services: 비즈니스 로직
- repositories: SQL 및 DB 접근
- schemas: API 응답 모델
- templates: HTML
- static: JavaScript / CSS
- config.py: 환경설정
- db.py: MySQL 연결
- main.py: 앱 진입점

## Run

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

브라우저:
http://127.0.0.1:8000


## Graph hierarchy

`Curriculum -> Subcategory -> Skill -> Job`

Subcategory는 `skill_category_map.is_primary = 1`의 DB 분류를 사용하며 학습순서를 의미하지 않습니다.
