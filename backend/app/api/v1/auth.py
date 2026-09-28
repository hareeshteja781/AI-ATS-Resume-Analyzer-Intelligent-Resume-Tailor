from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, get_current_active_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserLogin, UserResponse
from app.services.auth_service import login_user, register_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    user_in: UserCreate,
    db: Session = Depends(get_db),
) -> User:
    return register_user(db, user_in)


@router.post("/login", response_model=Token)
def login(
    credentials: UserLogin,
    db: Session = Depends(get_db),
) -> Token:
    return login_user(db, credentials)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_active_user)) -> User:
    return current_user


# TEMPORARY LOCAL-DEVELOPMENT CONVENIENCE — remove after project completion.
@router.post("/dev-test-login", response_model=Token)
def dev_test_login(
    db: Session = Depends(get_db),
) -> Token:
    if settings.is_production or settings.ENVIRONMENT.lower() != "development":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Development test login is disabled.",
        )

    user = db.query(User).filter(User.email == settings.TEST_USER_EMAIL.lower()).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configured test user was not found.",
        )

    return Token(
        access_token=create_access_token(str(user.id)),
        token_type="bearer",
    )


@router.get("/protected")
def protected(current_user: User = Depends(get_current_active_user)) -> dict[str, str]:
    return {"status": "ok", "email": current_user.email}
