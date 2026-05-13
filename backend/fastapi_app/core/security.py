from fastapi import Header, HTTPException, Query, status

from fastapi_app.core.config import get_settings


def require_backend_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    settings = get_settings()
    if not settings.backend_api_key or x_api_key != settings.backend_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid backend API key")


def require_dashboard_token(
    x_dashboard_token: str | None = Header(default=None, alias="X-Dashboard-Token"),
) -> None:
    settings = get_settings()
    if not settings.dashboard_token or x_dashboard_token != settings.dashboard_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dashboard token")


def require_order_write_access(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_dashboard_token: str | None = Header(default=None, alias="X-Dashboard-Token"),
) -> None:
    settings = get_settings()
    has_backend_access = bool(settings.backend_api_key and x_api_key == settings.backend_api_key)
    has_dashboard_access = bool(settings.dashboard_token and x_dashboard_token == settings.dashboard_token)
    if not has_backend_access and not has_dashboard_access:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid write credentials")


def verify_websocket_token(token: str | None = Query(default=None)) -> None:
    settings = get_settings()
    if not settings.dashboard_token or token != settings.dashboard_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid websocket token")
