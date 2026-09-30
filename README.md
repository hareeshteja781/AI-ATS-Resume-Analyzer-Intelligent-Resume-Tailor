# AI ATS Resume Analyzer & Intelligent Resume Tailor

An AI-powered full-stack application that analyzes resumes against job descriptions, evaluates ATS compatibility, and tailors resume content while preserving the original document design.

## Features
- Resume upload and parsing for PDF and DOCX
- Job description analysis and keyword matching
- ATS compatibility and section-level analysis
- AI-assisted resume tailoring
- Tailoring comparison and resume versioning
- Validation of AI-generated suggestions
- Role benchmarking and job-match analysis
- Embeddings and vector search

## Tech Stack
- Frontend: React, TypeScript, Vite, React Router, React Query, Tailwind CSS
- Backend: Python, FastAPI, SQLAlchemy, Pydantic, JWT
- AI: Gemini API, embeddings, vector search
- Data: PostgreSQL, pgvector, Redis, Cloudflare R2
- Background jobs: Celery
- DevOps: Docker

## Architecture
```text
frontend/   React + TypeScript
backend/    FastAPI API, models, services, and routes
worker/     Celery background processing
tests/      Automated tests
docs/       Project documentation
```

## Run Locally
```bash
docker compose up --build
```

Configure the required environment variables using the repository environment example files.

## Testing
```bash
cd backend
pytest
```
