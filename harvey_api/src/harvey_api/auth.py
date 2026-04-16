from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Annotated, Tuple

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()

# users.json lives at harvey_api/users.json — three levels up from auth.py
# (harvey_api/src/harvey_api/auth.py → harvey_api/src/harvey_api/ → harvey_api/src/ → harvey_api/)
_USERS_FILE = Path(__file__).resolve().parent.parent.parent / "users.json"


def _load_users() -> dict:
    if not _USERS_FILE.exists():
        raise RuntimeError(
            f"users.json not found at {_USERS_FILE}. "
            "Make sure the file exists next to pyproject.toml."
        )
    with open(_USERS_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_current_user(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
) -> Tuple[str, str]:
    users = _load_users()
    user = users.get(credentials.username)
    password_ok = user is not None and secrets.compare_digest(
        credentials.password.encode("utf-8"),
        user["password"].encode("utf-8"),
    )
    if not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username, user["role"]


# Convenience type — use as a FastAPI dependency annotation
CurrentUser = Annotated[Tuple[str, str], Depends(get_current_user)]
