from fastapi import Response

from config import config

REFRESH_COOKIE = "faclab_refresh"
# Only the auth endpoints ever receive the refresh token
REFRESH_COOKIE_PATH = "/api/auth"


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """HttpOnly so scripts can't read it; SameSite=Strict so other sites can't
    make the browser send it."""
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=config.JWT_REFRESH_TTL_SECONDS,
        path=REFRESH_COOKIE_PATH,
        domain=config.AUTH_COOKIE_DOMAIN,
        secure=config.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        domain=config.AUTH_COOKIE_DOMAIN,
        secure=config.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="strict",
    )
