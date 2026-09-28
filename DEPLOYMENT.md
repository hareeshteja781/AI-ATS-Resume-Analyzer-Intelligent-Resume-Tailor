# Deployment Guide

This project is designed for deployment to:
- Frontend: Vercel
- Backend: Render
- Background worker: Render worker
- PostgreSQL: managed PostgreSQL
- Redis: managed Redis (example: Upstash)
- File storage: Cloudflare R2

The production containers install LibreOffice for Linux-compatible DOCX-to-PDF conversion. PDF generation is not available in a runtime that has neither LibreOffice nor Windows Word.

## Required infrastructure

### Backend environment variables
Set these on Render before deployment:

- DATABASE_URL
- JWT_SECRET_KEY
- JWT_ALGORITHM=HS256
- ACCESS_TOKEN_EXPIRE_MINUTES=30
- REDIS_URL
- CELERY_BROKER_URL
- CELERY_RESULT_BACKEND
- ALLOWED_ORIGINS=https://your-frontend.vercel.app
- RATE_LIMIT_PER_MINUTE=120
- MAX_UPLOAD_SIZE_BYTES=10485760
- R2_ENDPOINT_URL
- R2_ACCESS_KEY_ID
- R2_SECRET_ACCESS_KEY
- R2_BUCKET_NAME
- R2_PUBLIC_URL

### Frontend environment variables
Set these on Vercel:

- VITE_API_URL=https://your-render-backend-url.onrender.com/api/v1

### Redis
Use managed Redis for Celery and job queue coordination. Example providers include Upstash or Redis Cloud.

### PostgreSQL
Use PostgreSQL 17 with the pgvector extension enabled and set DATABASE_URL to the connection string that matches the database provider. Alembic creates the `vector` extension during the embeddings migration; the deployment role must be allowed to create extensions or the provider must enable pgvector in advance.

### Cloudflare R2
Create a bucket and generate an access key pair. Store access values only in the deployment platform secret manager.

## Local development

1. Copy `.env.example` to `.env` in the repository root.
2. Update the values for local use.
3. Run:

```bash
docker compose up --build
```

This starts:
- PostgreSQL on port 5432
- Redis on port 6379
- FastAPI backend on port 8000
- background worker
- Vite frontend on port 5173

## Database migrations

Run migrations in the backend container or local backend environment:

```bash
cd backend
python -m alembic upgrade head
```

If you need to generate a migration after model changes:

```bash
cd backend
python -m alembic revision --autogenerate -m "describe change"
```

Important:
- Always run migrations against the production database via the Render shell or a controlled release process.
- Never commit real credentials.
- Use environment variables, not hard-coded secrets.

## Deployment flow

### 1. Frontend (Vercel)
- Import the repo into Vercel.
- Set the framework to Vite or use the repository root with the frontend project.
- Set `VITE_API_URL` to the Render backend URL.
- Trigger a production deployment after CI passes.

### 2. Backend (Render)
- Create a Python web service from the `backend` folder.
- Use the render service config in `render.yaml` as a starting point.
- Make sure the start command runs Alembic before Uvicorn.
- Add all required environment variables.
- Deploy only after you confirm values in the Render dashboard.

### 3. Worker (Render)
- Create a Render background worker service from the `worker` folder.
- Set the worker command to run Celery.
- Ensure Redis and database env vars are set.

The API liveness endpoint is `/health`; `/ready` verifies database and Redis connectivity and returns `503` when either dependency is unavailable.

## CI/CD

The repository includes a GitHub Actions workflow at `.github/workflows/ci.yml`.

CI checks:
- backend tests
- frontend tests
- lint
- TypeScript type checks
- production build

The workflow does not deploy automatically. Deployment must be triggered manually from the platform after verifying the pipeline and environment values.

## Do not commit secrets

Use the deployment environment secret manager or `.env` only on your local machine. The repository includes `.env.example` as a template for required keys, not actual credentials.
