from pathlib import Path
from typing import Any, Dict, Optional
import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.config import settings

bearer_scheme = HTTPBearer(auto_error=False)
_firebase_initialized = False


def init_firebase() -> bool:
    global _firebase_initialized
    if _firebase_initialized:
        return True

    cred_path = Path(settings.FIREBASE_CREDENTIALS_PATH)
    if cred_path.exists():
        cred = credentials.Certificate(str(cred_path))
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        return True
    return False


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Dict[str, Any]:
    """Verifies Firebase ID token from Authorization: Bearer <token> header."""
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Firebase authentication token.",
        )

    token = creds.credentials

    if not init_firebase():
        # Allows local Swagger/pytest testing before service account JSON is added
        if settings.ENVIRONMENT == "development" and token.startswith("dev-token:"):
            uid = token.split(":", 1)[1] or "dev_user"
            return {"uid": uid, "email": f"{uid}@local.dev"}
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Firebase Admin SDK credentials file not found on server.",
        )

    try:
        decoded_token = firebase_auth.verify_id_token(token)
        return {
            "uid": decoded_token["uid"],
            "email": decoded_token.get("email", ""),
            "name": decoded_token.get("name", ""),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired Firebase token: {str(e)}",
        )