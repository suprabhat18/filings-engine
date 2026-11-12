"""Google OAuth 2.0 sign-in check.

The frontend signs users in with Google and sends their Google ID token with every
request ("Authorization: Bearer <token>"). We verify the token's signature, expiry
and audience (our OAuth client ID) with Google's public keys before trusting it.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request, status

from .models import User

TokenVerifier = Callable[[str], User]


class GoogleTokenVerifier:
    def __init__(self, client_id: str, allowed_emails: set[str] | None = None) -> None:
        if not client_id:
            raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID is not set")
        from google.auth.transport import requests as google_requests

        self._client_id = client_id
        self._allowed = allowed_emails or set()
        self._transport = google_requests.Request()  # caches Google's signing keys

    def __call__(self, token: str) -> User:
        from google.oauth2 import id_token

        try:
            claims = id_token.verify_oauth2_token(token, self._transport, audience=self._client_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired sign-in") from exc
        if not claims.get("email_verified"):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google email is not verified")
        email = claims["email"].lower()
        if self._allowed and email not in self._allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is not on the access list")
        return User(
            uid=claims["sub"],
            email=email,
            name=claims.get("name", ""),
            picture=claims.get("picture", ""),
        )


def current_user(request: Request) -> User:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Sign in required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = request.app.state.services.verify_token(token)
    request.state.user = user
    return user


CurrentUser = Depends(current_user)
