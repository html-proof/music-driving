from fastapi import APIRouter, Depends, Response, status

from app.dependencies import DB, SettingsDep
from app.middleware.rate_limit import rate_limit
from app.schemas.auth import DeviceAuthRequest, DeviceAuthResponse, RefreshRequest, TokenPair
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/device", response_model=DeviceAuthResponse,
             dependencies=[Depends(rate_limit("device", 30, 3600))],
             summary="Create (first call) or resume this device's anonymous account")
async def device_auth(body: DeviceAuthRequest, db: DB, settings: SettingsDep, response: Response) -> DeviceAuthResponse:
    tokens, created = await AuthService(db, settings).device_login(body.device_id, body.device_secret,
                                                                   body.platform, body.name)
    if created:
        response.status_code = status.HTTP_201_CREATED
    return DeviceAuthResponse(**tokens.model_dump(), created=created)


@router.post("/refresh", response_model=TokenPair, dependencies=[Depends(rate_limit("refresh", 60, 300))])
async def refresh(body: RefreshRequest, db: DB, settings: SettingsDep) -> TokenPair:
    return await AuthService(db, settings).refresh(body.refresh_token)
