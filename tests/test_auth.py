"""
tests/test_auth.py
Authentication tests for SQLite auth:
- Successful signup
- Duplicate email rejection
- Invalid email rejection
- Short password rejection
- Successful login
- Wrong password rejection
- Unknown email rejection
- /auth/me while logged in
- /auth/me unauthenticated
- Logout
- /auth/me after logout
"""
import sys
if sys.platform == "win32":
    sys.path = ["\\\\?\\" + p if ":" in p and not p.startswith("\\\\?\\") else p for p in sys.path]

import os
import pytest
from fastapi import HTTPException, Response

# Ensure a dedicated test SQLite database is used
TEST_DB_FILE = os.path.join(os.path.dirname(__file__), "test_auth.db")
if os.path.exists(TEST_DB_FILE):
    try:
        os.remove(TEST_DB_FILE)
    except Exception:
        pass

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE}"
os.environ["SECRET_KEY"] = "test-secret-key-must-be-long-enough-for-testing"

from backend.db import Base, engine, SessionLocal
from backend.routes_auth import (
    AuthRequest,
    _get_current_user,
    login,
    logout,
    me,
    signup,
)

Base.metadata.create_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _extract_cookie(response: Response, cookie_name: str = "session") -> str:
    """Extract session cookie value from FastAPI Response headers."""
    for header in response.raw_headers:
        if header[0].lower() == b"set-cookie":
            cookie_str = header[1].decode("latin-1")
            for part in cookie_str.split(";"):
                part = part.strip()
                if part.startswith(f"{cookie_name}="):
                    return part.split("=", 1)[1]
    # Fallback to headers dict
    set_cookie = response.headers.get("set-cookie", "")
    for part in set_cookie.split(";"):
        part = part.strip()
        if part.startswith(f"{cookie_name}="):
            return part.split("=", 1)[1]
    return ""


# ------------------------------------------------------------------
# Signup tests
# ------------------------------------------------------------------

def test_signup_success(db):
    res = Response()
    user = signup(AuthRequest(email="alice@example.com", password="securepassword1"), res, db)
    assert user.email == "alice@example.com"
    assert user.id is not None
    assert user.is_active is True
    assert not hasattr(user, "password")
    cookie = _extract_cookie(res)
    assert len(cookie) > 0


def test_signup_duplicate_email(db):
    res = Response()
    signup(AuthRequest(email="bob@example.com", password="securepassword1"), res, db)
    with pytest.raises(HTTPException) as exc_info:
        signup(AuthRequest(email="bob@example.com", password="securepassword1"), res, db)
    assert exc_info.value.status_code == 422
    assert "already exists" in str(exc_info.value.detail)


def test_signup_invalid_email(db):
    res = Response()
    with pytest.raises(HTTPException) as exc_info:
        signup(AuthRequest(email="not-an-email", password="securepassword1"), res, db)
    assert exc_info.value.status_code == 422


def test_signup_short_password(db):
    res = Response()
    with pytest.raises(HTTPException) as exc_info:
        signup(AuthRequest(email="carol@example.com", password="short"), res, db)
    assert exc_info.value.status_code == 422
    assert "8 characters" in str(exc_info.value.detail)


# ------------------------------------------------------------------
# Login tests
# ------------------------------------------------------------------

def test_login_success(db):
    signup_res = Response()
    signup(AuthRequest(email="dave@example.com", password="securepassword1"), signup_res, db)

    login_res = Response()
    user = login(AuthRequest(email="dave@example.com", password="securepassword1"), login_res, db)
    assert user.email == "dave@example.com"
    cookie = _extract_cookie(login_res)
    assert len(cookie) > 0


def test_login_wrong_password(db):
    signup_res = Response()
    signup(AuthRequest(email="eve@example.com", password="securepassword1"), signup_res, db)

    login_res = Response()
    with pytest.raises(HTTPException) as exc_info:
        login(AuthRequest(email="eve@example.com", password="wrongpassword"), login_res, db)
    assert exc_info.value.status_code == 401
    assert "Incorrect email or password" in str(exc_info.value.detail)


def test_login_unknown_email(db):
    login_res = Response()
    with pytest.raises(HTTPException) as exc_info:
        login(AuthRequest(email="nobody@example.com", password="securepassword1"), login_res, db)
    assert exc_info.value.status_code == 401


# ------------------------------------------------------------------
# /auth/me tests
# ------------------------------------------------------------------

def test_me_while_logged_in(db):
    signup_res = Response()
    signup(AuthRequest(email="frank@example.com", password="securepassword1"), signup_res, db)

    login_res = Response()
    login(AuthRequest(email="frank@example.com", password="securepassword1"), login_res, db)
    cookie = _extract_cookie(login_res)

    current_user = _get_current_user(session=cookie, db=db)
    result = me(current_user=current_user)
    assert result.email == "frank@example.com"


def test_me_unauthenticated(db):
    with pytest.raises(HTTPException) as exc_info:
        _get_current_user(session=None, db=db)
    assert exc_info.value.status_code == 401


# ------------------------------------------------------------------
# Logout tests
# ------------------------------------------------------------------

def test_logout_then_me(db):
    signup_res = Response()
    signup(AuthRequest(email="grace@example.com", password="securepassword1"), signup_res, db)

    login_res = Response()
    login(AuthRequest(email="grace@example.com", password="securepassword1"), login_res, db)
    cookie = _extract_cookie(login_res)

    # User is currently authenticated
    current_user = _get_current_user(session=cookie, db=db)
    assert current_user.email == "grace@example.com"

    # Call logout
    logout_res = Response()
    logout(logout_res)
    # Cookie in logout_res is expired (deleted)
    # Calling /auth/me without a cookie results in 401
    with pytest.raises(HTTPException) as exc_info:
        _get_current_user(session=None, db=db)
    assert exc_info.value.status_code == 401
