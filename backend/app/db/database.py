from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.resolved_database_url,
    pool_pre_ping=True,
    future=True,
)


def validate_pgvector_extension() -> None:
    if not settings.resolved_database_url.startswith("postgresql"):
        return

    try:
        with engine.connect() as connection:
            row = connection.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first()
    except Exception as exc:  # pragma: no cover - environment guard for production PostgreSQL
        raise RuntimeError(
            "PostgreSQL pgvector extension is required for vector storage. "
            "Install the pgvector extension in the target database before starting the app."
        ) from exc

    if row is None:
        raise RuntimeError(
            "PostgreSQL pgvector extension is not enabled for this database. "
            "Enable the 'vector' extension before starting the app."
        )


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db() -> Generator[Session, None, None]:
    if settings.resolved_database_url.startswith("postgresql"):
        validate_pgvector_extension()

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    db = SessionLocal()
    try:
        print("Database session created successfully!")
    finally:
        db.close()
        print("Database session closed successfully!")