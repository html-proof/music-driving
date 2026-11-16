import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.models import User
from app.security import decode_access_token
from app.services.cache import Cache
from app.services.catalog_service import CatalogService
from app.services.lyrics_service import LyricsService

_bearer = HTTPBearer(auto_error=False)

DB = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_catalog(request: Request) -> CatalogService:
    return request.app.state.catalog


def get_cache(request: Request) -> Cache:
    return request.app.state.cache


def get_lyrics(request: Request) -> LyricsService:
    return request.app.state.lyrics


Catalog = Annotated[CatalogService, Depends(get_catalog)]
Lyrics = Annotated[LyricsService, Depends(get_lyrics)]


async def _user_from_token(db: AsyncSession, creds: HTTPAuthorizationCredentials | None) -> User | None:
    if creds is None:
        return None
    try:
        payload = decode_access_token(creds.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired access token", {"WWW-Authenticate": "Bearer"}
        ) from exc
    user = await db.get(User, user_id)
    if user is None or not user.is_active or payload.get("ver") != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session is no longer valid", {"WWW-Authenticate": "Bearer"})
    return user


async def current_user(
    db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> User:
    user = await _user_from_token(db, creds)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", {"WWW-Authenticate": "Bearer"})
    return user


async def optional_user(
    db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> User | None:
    return await _user_from_token(db, creds)


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]
