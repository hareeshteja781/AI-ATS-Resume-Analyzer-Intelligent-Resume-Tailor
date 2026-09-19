# AI ATS Resume Analyzer & Intelligent Resume Tailor

A production-style web application that analyzes resumes against job descriptions, evaluates ATS compatibility, and intelligently tailors resumes while preserving the user's original content and document design.

## Current Status

Project foundation is being built incrementally.

### Backend
- Python
- FastAPI
- SQLAlchemy
- PostgreSQL
- Pydantic Settings

### Planned Architecture
- React + Vite frontend
- FastAPI backend
- Celery worker
- Redis
- PostgreSQL + pgvector
- Gemini API
- Cloudflare R2

## Project Structure

```text
resume-ats-platform/
├── backend/
├── frontend/
├── worker/
├── tests/
├── docs/
└── README.md