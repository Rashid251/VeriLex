"""
backend/routes_auth.py
FastAPI router for /auth/* endpoints.
Sessions are stored in a signed server-side cookie via itsdangerous.
"""
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import authenticate_user, create_user, validate_email
from backend.db import User, get_db

router = APIRouter(prefix="/auth", tags=["auth"])

# ------------------------------------------------------------------
# Cookie / session config
# ------------------------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-please")
SESSION_COOKIE = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days in seconds

_signer = URLSafeTimedSerializer(SECRET_KEY)

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = "none" if COOKIE_SECURE else "lax"


def _make_session_token(user_id: int) -> str:
    payload = json.dumps({"user_id": user_id})
    return _signer.dumps(payload)


def _decode_session_token(token: str) -> int:
    try:
        raw = _signer.loads(token, max_age=SESSION_MAX_AGE)
        data = json.loads(raw)
        return int(data["user_id"])
    except (SignatureExpired, BadSignature, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please log in again.",
        )


def _set_session_cookie(response: Response, user_id: int) -> None:
    token = _make_session_token(user_id)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        max_age=SESSION_MAX_AGE,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
    )


def _get_current_user(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> User:
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    user_id = _decode_session_token(session)
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated.",
        )
    return user


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------

class AuthRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    created_at: datetime
    is_active: bool

    model_config = {"from_attributes": True}


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def signup(body: AuthRequest, response: Response, db: Session = Depends(get_db)):
    try:
        user = create_user(db, body.email, body.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    _set_session_cookie(response, user.id)
    return user


@router.post("/login", response_model=UserOut)
def login(body: AuthRequest, response: Response, db: Session = Depends(get_db)):
    try:
        email = validate_email(body.email)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    user = authenticate_user(db, email, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    _set_session_cookie(response, user.id)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    _clear_session_cookie(response)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(_get_current_user)):
    return current_user
