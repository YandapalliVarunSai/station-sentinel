from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from station_health.supplied import TOKENS


bearer = HTTPBearer(auto_error=False)


def authenticated_operator(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> int:
    operator_id = TOKENS.get(credentials.credentials) if credentials else None
    if operator_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return operator_id
