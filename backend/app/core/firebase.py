"""
Firebase authentication helper.

Verifies the Firebase ID token from the Authorization: Bearer <token> header
and returns the decoded user info (uid, email, name).


"""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

import firebase_admin
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as firebase_auth, credentials

from app.config import settings

bearer_scheme       = HTTPBearer(auto_error=False)
_firebase_initialized = False


def _init_firebase() -> bool:
    """
    Initialises the Firebase Admin SDK once using the service account JSON.
    Returns True if initialised successfully, False if the credentials file is missing.
    """
    global _firebase_initialized
    if _firebase_initialized:
        return True

    cred_path = Path(settings.FIREBASE_CREDENTIALS_PATH)
    if not cred_path.exists():
        return False

    firebase_admin.initialize_app(credentials.Certificate(str(cred_path)))
    _firebase_initialized = True
    return True


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Dict[str, Any]:
    """
    FastAPI dependency that authenticates every protected endpoint.

    Returns a dict with 'uid', 'email', and 'name' on success.
    Raises HTTP 401 on missing or invalid tokens.
    """
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Firebase authentication token.",
        )

    token = creds.credentials

    if not _init_firebase():
        # Allow simple dev-token testing before the Firebase service account is set up
        if settings.ENVIRONMENT == "development" and token.startswith("dev-token:"):
            uid = token.split(":", 1)[1] or "dev_user"
            return {"uid": uid, "email": f"{uid}@local.dev", "name": "Dev User"}

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Firebase Admin SDK credentials not found on the server.",
        )

    try:
        decoded = None
        for attempt in range(2):
            try:
                # Firebase's certificate fetch is synchronous. Keep it off
                # FastAPI's event loop and retry one transient disconnect.
                decoded = await asyncio.to_thread(firebase_auth.verify_id_token, token)
                break
            except firebase_auth.CertificateFetchError:
                if attempt == 1:
                    raise
                await asyncio.sleep(0.25)
        return {
            "uid":   decoded["uid"],
            "email": decoded.get("email", ""),
            "name":  decoded.get("name", ""),
        }
    except firebase_auth.CertificateFetchError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase could not be reached to verify your session. Retry the request shortly; the token was not marked invalid.",
            headers={"Retry-After": "2"},
        ) from exc
    except firebase_auth.InvalidIdTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase ID token is invalid or expired. Refresh your session and try again.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase ID token is invalid or expired. Refresh your session and try again.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase token verification is temporarily unavailable. Retry the request shortly.",
            headers={"Retry-After": "2"},
        ) from exc
