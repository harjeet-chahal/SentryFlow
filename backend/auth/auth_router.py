"""User authentication and API-key management.

Two distinct credentials live here and they are not interchangeable:

    JWT           Identifies a human operating the dashboard. Short-lived,
                  refreshed via /auth/refresh.
    API key       Identifies a machine calling through the gateway. Long-lived,
                  revocable, and the thing the rate limiter keys on.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.auth.schemas import (
    ApiKeyCreate,
    ApiKeyResponse,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserDirectory,
    UserResponse,
)
from backend.config import JWT_SECRET, settings
from backend.middlewares.auth_middleware import invalidate_api_key
from backend.models.database import SessionLocal
from backend.models.models import ApiKey, User

logger = logging.getLogger(__name__)

router = APIRouter()

# bcrypt is deliberately slow (~200 ms of CPU), and every query here is a
# network round trip. Both run in the threadpool -- routes and dependencies
# that do no async work are plain ``def``, which FastAPI runs there. On the
# event loop they would stall every in-flight gateway request.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Distinguishes the two token flavours. Without this claim a refresh token
# would be accepted as an access token, silently extending its privileges to
# every authenticated route.
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def get_user(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def authenticate_user(db: Session, username: str, password: str):
    user = get_user(db, username)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    payload = {
        "sub": subject,
        "type": token_type,
        "exp": datetime.now(timezone.utc) + expires_delta,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def issue_token_pair(username: str) -> dict:
    return {
        "access_token": create_token(
            username, ACCESS_TOKEN_TYPE, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        ),
        "refresh_token": create_token(
            username, REFRESH_TOKEN_TYPE, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        ),
        "token_type": "bearer",
    }


def decode_token(token: str, expected_type: str) -> str:
    """Decode a token and confirm it is the flavour the caller expects."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise credentials_exception

    if payload.get("type") != expected_type:
        raise credentials_exception

    username = payload.get("sub")
    if not username:
        raise credentials_exception
    return username


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    username = decode_token(token, ACCESS_TOKEN_TYPE)
    user = get_user(db, username=username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require an administrator.

    A signed-in non-admin gets 403 rather than 401: they are authenticated,
    and re-authenticating would not change the answer.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required"
        )
    return current_user


def scoped_user_id(current_user: User, requested: Optional[str]) -> Optional[str]:
    """Whose data a request may see. ``None`` means every user's.

    Admins may look at anyone, or at everyone. Other users see only
    themselves, and naming someone else is refused rather than quietly
    ignored, so a client bug cannot pass for an empty result.
    """
    if current_user.is_admin:
        return requested or None
    if requested and requested != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only view your own data"
        )
    return current_user.id


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def signup(user: UserCreate, db: Session = Depends(get_db)):
    existing = (
        db.query(User)
        .filter((User.username == user.username) | (User.email == user.email))
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered",
        )

    db_user = User(
        email=user.email,
        username=user.username,
        hashed_password=get_password_hash(user.password),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post("/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Exchange credentials for a token pair.

    Takes form encoding rather than JSON to stay compatible with the OAuth2
    password flow, which is what Swagger's Authorize button and the standard
    client libraries speak.
    """
    user = await run_in_threadpool(authenticate_user, db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return issue_token_pair(user.username)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    """Trade a valid refresh token for a fresh pair."""
    username = decode_token(payload.refresh_token, REFRESH_TOKEN_TYPE)
    user = get_user(db, username=username)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return issue_token_pair(user.username)


@router.post("/apikeys/create", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    api_key_data: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_api_key = ApiKey(
        key=secrets.token_hex(32),
        name=api_key_data.name,
        user_id=current_user.id,
    )
    db.add(db_api_key)
    db.commit()
    db.refresh(db_api_key)
    return db_api_key


@router.get("/apikeys", response_model=List[ApiKeyResponse])
def list_api_keys(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return db.query(ApiKey).filter(ApiKey.user_id == current_user.id).all()


def _deactivate_api_key(db: Session, api_key_id: str, user_id: str) -> Optional[str]:
    """Deactivate one of a user's keys. Returns the key, or None if not theirs."""
    record = (
        db.query(ApiKey)
        .filter(ApiKey.id == api_key_id, ApiKey.user_id == user_id)
        .first()
    )
    if record is None:
        return None
    record.is_active = False
    db.commit()
    return record.key


@router.delete("/apikeys/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    api_key_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke a key and evict it from the gateway's cache.

    Deactivating the row alone is not enough: the gateway caches resolved
    keys for an hour, so a revoked key would keep working until that expired.
    """
    key = await run_in_threadpool(_deactivate_api_key, db, api_key_id, current_user.id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    await invalidate_api_key(key)
    return None


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    return current_user


def _contains(text: str) -> str:
    """A LIKE pattern matching ``text`` anywhere, with wildcards taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/users", response_model=UserDirectory)
def list_users(
    search: Optional[str] = Query(None, max_length=100, description="Part of a username or email"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Accounts in username order, for administrators choosing a user.

    Searched and paged in the database, so a picker never loads every
    account to show a few.
    """
    query = db.query(User)
    if search:
        pattern = _contains(search)
        query = query.filter(
            or_(User.username.ilike(pattern, escape="\\"), User.email.ilike(pattern, escape="\\"))
        )
    total = query.count()
    users = query.order_by(User.username).offset(offset).limit(limit).all()
    return {"total": total, "users": users}
