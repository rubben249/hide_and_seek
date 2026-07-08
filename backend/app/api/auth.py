from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.crud import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
    get_leaderboard,
    verify_password,
)
from app.db.database import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        v = v.strip()
        if not (3 <= len(v) <= 32):
            raise ValueError("Username must be 3–32 characters")
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username may only contain letters, numbers, _ and -")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    user_id: str


class ProfileResponse(BaseModel):
    user_id: str
    username: str
    email: str
    created_at: datetime
    games_played: int
    wins: int
    losses: int
    win_rate: float


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _create_token(user_id: str, username: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str | None:
    if credentials is None:
        return None
    payload = decode_token(credentials.credentials)
    return payload["sub"] if payload else None


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    user_id = await get_current_user_id(credentials)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if await get_user_by_username(db, body.username):
        raise HTTPException(status_code=409, detail="Username already taken")
    if await get_user_by_email(db, body.email):
        raise HTTPException(status_code=409, detail="Email already registered")

    user = await create_user(db, body.username, body.email, body.password)
    return TokenResponse(
        access_token=_create_token(user.id, user.username),
        username=user.username,
        user_id=user.id,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await get_user_by_username(db, body.username)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return TokenResponse(
        access_token=_create_token(user.id, user.username),
        username=user.username,
        user_id=user.id,
    )


@router.get("/me", response_model=ProfileResponse)
async def get_profile(
    user_id: str = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    stats = user.stats
    gp = stats.games_played if stats else 0
    wins = stats.wins if stats else 0
    losses = stats.losses if stats else 0

    return ProfileResponse(
        user_id=user.id,
        username=user.username,
        email=user.email,
        created_at=user.created_at,
        games_played=gp,
        wins=wins,
        losses=losses,
        win_rate=round(wins / gp * 100, 1) if gp else 0.0,
    )


@router.get("/leaderboard")
async def leaderboard(db: AsyncSession = Depends(get_db)):
    return {"leaderboard": await get_leaderboard(db)}
