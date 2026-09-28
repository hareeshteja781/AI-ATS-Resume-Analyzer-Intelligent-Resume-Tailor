import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.models.user import User

SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_register_user_success(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "newuser@example.com", "password": "StrongPass123!"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["is_active"] is True
    assert "password_hash" not in data


def test_login_returns_token(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "loginuser@example.com", "password": "StrongPass123!"},
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "loginuser@example.com", "password": "StrongPass123!"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_rejects_invalid_credentials(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "badlogin@example.com", "password": "StrongPass123!"},
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "badlogin@example.com", "password": "WrongPassword!"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_register_rejects_duplicate_email(client):
    payload = {"email": "duplicate@example.com", "password": "StrongPass123!"}
    first = client.post("/api/v1/auth/register", json=payload)
    second = client.post("/api/v1/auth/register", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"] == "Email already registered"


def test_protected_route_requires_valid_token(client):
    register = client.post(
        "/api/v1/auth/register",
        json={"email": "protected@example.com", "password": "StrongPass123!"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "protected@example.com", "password": "StrongPass123!"},
    ).json()["access_token"]

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    no_auth = client.get("/api/v1/auth/me")

    assert register.status_code == 201
    assert me.status_code == 200
    assert me.json()["email"] == "protected@example.com"
    assert no_auth.status_code == 401


def test_inactive_user_cannot_login(client):
    db = TestingSessionLocal()
    user = User(
        email="inactive@example.com",
        password_hash=hash_password("StrongPass123!"),
        is_active=False,
    )
    db.add(user)
    db.commit()
    db.close()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@example.com", "password": "StrongPass123!"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Inactive user"


def test_dev_login_is_disabled_outside_development(client, monkeypatch):
    monkeypatch.setattr("app.api.v1.auth.settings.ENVIRONMENT", "production")
    response = client.post("/api/v1/auth/dev-test-login")

    assert response.status_code == 404
    assert "disabled" in response.json()["detail"].lower()
