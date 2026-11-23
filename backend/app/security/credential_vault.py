import re
from typing import Dict, List, Optional
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session
from app.config import settings
from app.database.models import UserCredential

VAULT_PATTERN = re.compile(r"\{\{VAULT:([a-zA-Z0-9_-]+)\}\}")


class CredentialVault:
    def __init__(self, encryption_key: Optional[str] = None):
        key = encryption_key or settings.VAULT_ENCRYPTION_KEY
        if not key:
            # Generate an ephemeral key only if none configured (warn in production)
            key = Fernet.generate_key().decode()
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")

    def store_credential(
        self, db: Session, user_id: str, label: str, domain: str, username: str, password: str
    ) -> UserCredential:
        existing = (
            db.query(UserCredential)
            .filter(UserCredential.user_id == user_id, UserCredential.label == label)
            .first()
        )
        encrypted_pw = self.encrypt(password)
        if existing:
            existing.domain = domain
            existing.username = username
            existing.encrypted_password = encrypted_pw
            db.commit()
            db.refresh(existing)
            return existing

        cred = UserCredential(
            user_id=user_id,
            label=label,
            domain=domain,
            username=username,
            encrypted_password=encrypted_pw,
        )
        db.add(cred)
        db.commit()
        db.refresh(cred)
        return cred

    def list_credentials_for_prompt(self, db: Session, user_id: str) -> List[Dict[str, str]]:
        """Returns safe metadata & placeholders (NEVER raw passwords) for the LLM planner."""
        rows = db.query(UserCredential).filter(UserCredential.user_id == user_id).all()
        return [
            {
                "label": r.label,
                "domain": r.domain,
                "username": r.username,
                "password_placeholder": f"{{{{VAULT:{r.label}}}}}",
            }
            for r in rows
        ]

    def resolve_text(self, db: Session, user_id: str, raw_text: str) -> str:
        """Replaces {{VAULT:label}} with the decrypted password inside BrowserActions only."""
        def _replace(match: re.Match) -> str:
            label = match.group(1)
            cred = (
                db.query(UserCredential)
                .filter(UserCredential.user_id == user_id, UserCredential.label == label)
                .first()
            )
            if not cred:
                raise ValueError(f"Credential '{label}' not found in vault for user.")
            return self.decrypt(cred.encrypted_password)

        return VAULT_PATTERN.sub(_replace, raw_text)

    @staticmethod
    def mask_sensitive_text(text: str) -> str:
        """Masks any resolved secret before saving logs or screenshots metadata."""
        return VAULT_PATTERN.sub("********", text)