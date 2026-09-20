import uuid

from fastapi import Request, Response

import config

COOKIE_NAME = "anon_id"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def resolve_id(request: Request) -> str:
    """Cookie if the browser already has one; otherwise a freshly generated
    id. This is a soft signal only -- clearing cookies or switching browsers
    resets it -- the real cost backstop is the global daily cap in
    limits/rate_limiter.py.
    """
    existing = request.cookies.get(COOKIE_NAME)
    return existing if existing else str(uuid.uuid4())


def set_cookie(response: Response, anon_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        anon_id,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite=config.COOKIE_SAMESITE,
        secure=config.COOKIE_SECURE,
    )


def resolve_identity(request: Request, response: Response) -> str:
    """Convenience wrapper for the common case: resolve + set on the same
    response object FastAPI already injected."""
    anon_id = resolve_id(request)
    set_cookie(response, anon_id)
    return anon_id
