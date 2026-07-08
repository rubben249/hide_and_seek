from __future__ import annotations

from datetime import datetime, timezone

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import GameParticipant, GameRecord, User, UserStats


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


async def create_user(db: AsyncSession, username: str, email: str, password: str) -> User:
    user = User(username=username, email=email, password_hash=hash_password(password))
    db.add(user)
    await db.flush()
    stats = UserStats(user_id=user.id)
    db.add(stats)
    await db.commit()
    await db.refresh(user)
    return user


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(
        select(User).where(User.username == username).options(selectinload(User.stats))
    )
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(
        select(User).where(User.id == user_id).options(selectinload(User.stats))
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Game records
# ---------------------------------------------------------------------------

async def record_game_result(
    db: AsyncSession,
    mode: str,
    end_reason: str,
    winner_username: str | None,
    turn_count: int,
    participant_data: list[dict],  # [{"user_id": ..., "won": bool}, ...]
) -> GameRecord:
    record = GameRecord(
        mode=mode,
        end_reason=end_reason,
        winner_username=winner_username,
        finished_at=datetime.now(timezone.utc),
        turn_count=turn_count,
    )
    db.add(record)
    await db.flush()

    for p in participant_data:
        participant = GameParticipant(
            game_id=record.id,
            user_id=p["user_id"],
            won=p["won"],
        )
        db.add(participant)

        user_result = await db.execute(
            select(UserStats).where(UserStats.user_id == p["user_id"])
        )
        stats = user_result.scalar_one_or_none()
        if stats:
            stats.games_played += 1
            if p["won"]:
                stats.wins += 1
            else:
                stats.losses += 1

    await db.commit()
    return record


async def get_leaderboard(db: AsyncSession, limit: int = 20) -> list[dict]:
    result = await db.execute(
        select(User, UserStats)
        .join(UserStats, User.id == UserStats.user_id)
        .order_by(UserStats.wins.desc(), UserStats.games_played.asc())
        .limit(limit)
    )
    rows = result.all()
    return [
        {
            "username": u.username,
            "games_played": s.games_played,
            "wins": s.wins,
            "losses": s.losses,
            "win_rate": round(s.wins / s.games_played * 100, 1) if s.games_played else 0,
        }
        for u, s in rows
    ]
