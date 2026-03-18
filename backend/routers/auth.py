"""
Authentication Router – JWT-Based User Auth
===========================================

Provides three endpoints for user self-service authentication:
  - ``POST /auth/register`` – create a new account
  - ``POST /auth/login``    – exchange credentials for a JWT
  - ``GET  /auth/me``       – return the authenticated user's profile

Token format:
  HS256-signed JWT containing the claims ``sub`` (user ID as string),
  ``username``, and ``exp`` (expiry timestamp). Tokens are valid for 24 hours.

Security notes:
  - Passwords are hashed with bcrypt via passlib's ``CryptContext``. The
    plaintext password is never stored or logged.
  - ``SECRET_KEY`` must be set as an environment variable. The application
    refuses to start if it is absent (raised at module import time).
  - The ``get_current_user`` function is exported for use by other routers
    that require an authenticated user (e.g. ``warnings.py``).

Dependencies:
  python-jose[cryptography], passlib[bcrypt], sqlalchemy

Author: <project maintainer>
"""

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["Auth"])

# SECRET_KEY is required at startup; raise immediately rather than fail at
# the first authenticated request, which would be harder to diagnose.
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is not set")

ALGORITHM          = "HS256"
TOKEN_EXPIRE_HOURS = 24   # JWT lifetime in hours

# passlib CryptContext handles bcrypt hashing and automatic algorithm upgrades.
# deprecated="auto" means older hash schemes are transparently rehashed on login.
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# tokenUrl tells FastAPI's auto-generated /docs UI where to obtain a token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _hash(password: str) -> str:
    """Hash a plaintext password using bcrypt.

    Args:
        password: The plaintext password string to hash.

    Returns:
        A bcrypt hash string suitable for storage in the ``hashed_password``
        column.
    """
    return _pwd.hash(password)


def _verify(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash.

    Args:
        plain: The plaintext password provided by the user at login.
        hashed: The bcrypt hash retrieved from the database.

    Returns:
        ``True`` if the plaintext matches the hash, ``False`` otherwise.
    """
    return _pwd.verify(plain, hashed)


def _make_token(user_id: int, username: str) -> str:
    """Create a signed HS256 JWT for the given user.

    The token payload contains:
      - ``sub``: The user's integer ID encoded as a string (standard JWT subject claim).
      - ``username``: The login handle, included for convenience so the frontend
        can display it without an extra ``/auth/me`` call.
      - ``exp``: Expiry timestamp (current UTC time + TOKEN_EXPIRE_HOURS).

    Args:
        user_id: The user's database primary key.
        username: The user's login handle.

    Returns:
        A compact JWT string that can be sent in an ``Authorization: Bearer``
        header.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": str(user_id), "username": username, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency that resolves a Bearer token to an authenticated User.

    Decodes and validates the JWT, then loads the corresponding ``User`` row
    from the database. Raises ``HTTP 401`` for any failure condition (invalid
    signature, expired token, unknown user) so that attackers cannot distinguish
    between the failure causes.

    This function is exported and used as a dependency by all routers that
    require authentication (e.g. ``GET /warnings/``, ``POST /warnings/``).

    Args:
        token: JWT extracted from the ``Authorization: Bearer <token>`` header
               by FastAPI's ``OAuth2PasswordBearer`` scheme.
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        The authenticated ``User`` ORM instance.

    Raises:
        HTTPException(401): When the token is missing, has an invalid signature,
            is expired, has a malformed payload, or references a non-existent
            user ID.
    """
    try:
        payload  = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id  = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new user account.

    Validates that neither the email address nor the username is already taken,
    then inserts a new row into the ``users`` table with a bcrypt-hashed
    password.

    Args:
        body: Registration data containing ``email``, ``username``, and
              ``password``.
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        The newly created user profile as a ``UserOut`` object (without
        the hashed password).

    Raises:
        HTTPException(400): When the email or username is already registered.
    """
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(400, "Email already registered")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(400, "Username already taken")
    user = User(
        email=body.email,
        username=body.username,
        hashed_password=_hash(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate a user and issue a JWT access token.

    Looks up the user by username and verifies the supplied password against
    the stored bcrypt hash. Returns a signed JWT on success.

    Args:
        body: Login credentials containing ``username`` and ``password``.
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A ``TokenResponse`` with ``access_token`` (JWT) and
        ``token_type="bearer"``.

    Raises:
        HTTPException(401): When the username does not exist or the password
            is incorrect. A generic error message is used intentionally to
            prevent user enumeration.
    """
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not _verify(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    return TokenResponse(access_token=_make_token(user.id, user.username))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    """Return the profile of the currently authenticated user.

    Requires a valid ``Authorization: Bearer <token>`` header. The token is
    validated by the ``get_current_user`` dependency.

    Args:
        current_user: The authenticated ``User`` ORM instance, resolved by
                      the ``get_current_user`` dependency.

    Returns:
        The user's public profile as a ``UserOut`` object.
    """
    return current_user
