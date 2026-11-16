from datetime import UTC, datetime

from fastapi import APIRouter, status
from sqlalchemy import select

from app.dependencies import DB, CurrentUser, SettingsDep
from app.models import Device, User
from app.schemas.auth import (
    DeviceOut,
    DeviceRegister,
    NotificationPrefs,
    NotificationPrefsUpdate,
    Preferences,
    PreferencesUpdate,
    ProfileUpdate,
    UserOut,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/users", tags=["users"])


def user_out(user: User) -> UserOut:
    p, prefs, notif = user.profile, user.preferences, user.notification_preferences
    return UserOut(
        id=user.id,
        display_name=p.display_name if p else "Listener",
        avatar_url=p.avatar_url if p else None,
        country=p.country if p else None,
        created_at=user.created_at,
        preferences=Preferences(languages=prefs.languages, audio_quality=prefs.audio_quality,
                                allow_explicit=prefs.allow_explicit) if prefs else Preferences(),
        notifications=NotificationPrefs(new_releases=notif.new_releases, recommendations=notif.recommendations,
                                        followed_artists=notif.followed_artists) if notif else NotificationPrefs(),
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return user_out(user)


@router.patch("/me", response_model=UserOut)
async def update_profile(body: ProfileUpdate, user: CurrentUser, db: DB) -> UserOut:
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user.profile, field, value.upper() if field == "country" and value else value)
    await db.commit()
    await db.refresh(user)
    return user_out(user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(user: CurrentUser, db: DB, settings: SettingsDep) -> None:
    """Permanently deletes this device's account and all of its playlists, likes, history and
    sessions. The app then starts over with a fresh anonymous account."""
    await AuthService(db, settings).delete_account(user)


@router.get("/me/preferences", response_model=Preferences)
async def get_preferences(user: CurrentUser) -> Preferences:
    return user_out(user).preferences


@router.patch("/me/preferences", response_model=Preferences)
async def update_preferences(body: PreferencesUpdate, user: CurrentUser, db: DB) -> Preferences:
    for field, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(user.preferences, field, value)
    await db.commit()
    await db.refresh(user)
    return user_out(user).preferences


@router.get("/me/notifications", response_model=NotificationPrefs)
async def get_notifications(user: CurrentUser) -> NotificationPrefs:
    return user_out(user).notifications


@router.patch("/me/notifications", response_model=NotificationPrefs)
async def update_notifications(body: NotificationPrefsUpdate, user: CurrentUser, db: DB) -> NotificationPrefs:
    for field, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(user.notification_preferences, field, value)
    await db.commit()
    await db.refresh(user)
    return user_out(user).notifications


def _device_out(d: Device) -> DeviceOut:
    return DeviceOut(id=d.id, installation_id=d.installation_id, platform=d.platform, name=d.name,
                     has_push_token=bool(d.push_token), last_seen_at=d.last_seen_at)


@router.put("/me/devices", response_model=DeviceOut)
async def register_device(body: DeviceRegister, user: CurrentUser, db: DB) -> DeviceOut:
    device = await db.scalar(
        select(Device).where(Device.user_id == user.id, Device.installation_id == body.installation_id)
    )
    if device is None:
        device = Device(user_id=user.id, installation_id=body.installation_id, platform=body.platform)
        db.add(device)
    device.platform = body.platform
    device.name = body.name
    if body.push_token is not None:
        device.push_token = body.push_token or None
    device.last_seen_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(device)
    return _device_out(device)


@router.get("/me/devices", response_model=list[DeviceOut])
async def list_devices(user: CurrentUser, db: DB) -> list[DeviceOut]:
    rows = (await db.scalars(select(Device).where(Device.user_id == user.id).order_by(Device.last_seen_at.desc()))).all()
    return [_device_out(d) for d in rows]
