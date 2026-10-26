"""
backend/auth.py
Password hashing, session cookie helpers, and user CRUD helpers.
"""
import re
from typing import Optional

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy.orm import Session

from backend.db import User

# ------------------------------------------------------------------
# Password hashing – Argon2 via pwdlib
# ------------------------------------------------------------------
_hasher = PasswordHash([Argon2Hasher()])

MIN_PASSWORD_LENGTH = 8

# Simple email regex (RFC 5321 simplified)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(plain, hashed)
    except Exception:
        return False


def validate_email(email: str) -> str:
    """Return normalised email or raise ValueError."""
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("Invalid email address.")
    return email


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )


# ------------------------------------------------------------------
# User CRUD
# ------------------------------------------------------------------

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


def create_user(db: Session, email: str, password: str) -> User:
    email = validate_email(email)
    validate_password(password)

    if get_user_by_email(db, email):
        raise ValueError("A user with that email already exists.")

    user = User(
        email=email,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    email = validate_email(email)
    user = get_user_by_email(db, email)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
