"""Errors with a stable machine-readable code.

Responses look like {"detail": "<English message>", "code": "<code>"}. The website
shows its own translation for each code (it supports six languages) and falls back
to the English `detail` for anything it does not know.
"""

from __future__ import annotations

from fastapi import HTTPException


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, detail: str, headers: dict | None = None):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


# Daily-limit messages, shared by the signed-in and the free search.
USER_QUOTA = "You've used all your searches for today on this account. They reset at midnight UTC."
GLOBAL_QUOTA = (
    "This demo has reached its daily search limit across all visitors, which keeps its "
    "costs down. Please try again tomorrow."
)
FREE_USED = "You've used your free question. Sign in with Google to keep asking."
FREE_LIMIT = "Today's free questions are used up. Sign in with Google to keep asking."
