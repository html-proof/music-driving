import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationPreferences, User, UserPreferences, UserProfile


async def get_by_device_id(db: AsyncSession, device_id: str) -> User | None:
    return await db.scalar(select(User).where(User.device_id == device_id))


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


def new_device_user(device_id: str, secret_hash: str, display_name: str, languages: list[str]) -> User:
    user = User(device_id=device_id, secret_hash=secret_hash)
    user.profile = UserProfile(display_name=display_name)
    user.preferences = UserPreferences(languages=languages, audio_quality="high", allow_explicit=True)
    user.notification_preferences = NotificationPreferences()
    return user
