"""
CredentialVault – stores and retrieves encrypted user credentials.

Passwords are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) before they
are written to the database. The LLM planner never sees raw passwords; it only
sees {{VAULT:label}} placeholders that StepExecutor resolves at the last moment.

Flow:
  User stores credential → encrypted in DB
  LLM plans a type action with text="{{VAULT:my_label}}"
  StepExecutor calls resolve_text() → decrypts and fills the real password
  Logs store "{{VAULT:my_label}}" (masked) so secrets never appear in history
"""

import re
from typing import Dict, List, Optional

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import CredentialField, UserCredential

# Matches {{VAULT:some_label}} tokens inside action parameters
# Labels are user-facing names and may contain spaces or punctuation. Capture
# any non-brace text so those labels resolve exactly instead of being typed as a
# literal `{{VAULT:...}}` password by the browser.
VAULT_TOKEN_PATTERN = re.compile(r"\{\{VAULT:([^{}]+)\}\}")
VAULT_FIELD_TOKEN_PATTERN = re.compile(r"\{\{VAULT_FIELD:(\d+):(\d+)\}\}")


class CredentialVault:
    def __init__(self, encryption_key: Optional[str] = None):
        key = encryption_key or settings.VAULT_ENCRYPTION_KEY

        if not key:
            # Generate a temporary key (data won't survive server restart — warn in prod)
            key = Fernet.generate_key().decode()

        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    # ── Encryption / Decryption ───────────────────────────────────────────────

    def encrypt(self, plaintext: str) -> str:
        """Encrypts a plaintext string and returns a URL-safe base64 ciphertext."""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypts a ciphertext string back to plaintext."""
        return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")

    # ── Storage ───────────────────────────────────────────────────────────────

    def store_credential(
        self,
        db: Session,
        user_id: str,
        label: str,
        domain: str,
        username: str,
        password: str,
        fields: Optional[Dict[str, str]] = None,
    ) -> UserCredential:
        """
        Saves an encrypted credential. If a credential with the same label already
        exists for this user, it is updated in place.
        """
        encrypted_pw = self.encrypt(password)

        existing = (
            db.query(UserCredential)
            .filter(UserCredential.user_id == user_id, UserCredential.label == label)
            .first()
        )

        if existing:
            # Update existing credential
            existing.domain             = domain
            existing.username           = username
            existing.encrypted_password = encrypted_pw
            self._replace_fields(db, user_id, existing.id, fields or {})
            db.commit()
            db.refresh(existing)
            return existing

        # Create new credential
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
        self._replace_fields(db, user_id, cred.id, fields or {})
        return cred

    def _replace_fields(self, db: Session, user_id: str, credential_id: int, fields: Dict[str, str]) -> None:
        prepared = []
        seen_names = set()
        for name, value in fields.items():
            clean_name = str(name).strip()
            clean_value = str(value)
            if not clean_name or not clean_value:
                continue
            key = clean_name.casefold()
            if len(clean_name) > 100 or len(clean_value) > 10000:
                raise ValueError("Vault field names must be at most 100 characters and values at most 10,000 characters.")
            if key in seen_names:
                raise ValueError(f"Duplicate vault field name: {clean_name}")
            seen_names.add(key)
            prepared.append((clean_name, key, clean_value))

        db.query(CredentialField).filter(
            CredentialField.user_id == user_id,
            CredentialField.credential_id == credential_id,
        ).delete(synchronize_session=False)
        for clean_name, key, clean_value in prepared:
            db.add(CredentialField(
                credential_id=credential_id,
                user_id=user_id,
                name=clean_name,
                name_key=key,
                encrypted_value=self.encrypt(clean_value),
            ))
        db.commit()

    def update_credential(
        self, db: Session, credential: UserCredential, label: str, domain: str,
        username: str, password: Optional[str], fields: Dict[str, str],
    ) -> UserCredential:
        credential.label = label.strip()
        credential.domain = domain.strip()
        credential.username = username
        if password:
            credential.encrypted_password = self.encrypt(password)
        self._replace_fields(db, credential.user_id, credential.id, fields)
        db.commit()
        db.refresh(credential)
        return credential

    def delete_credential(self, db: Session, credential: UserCredential) -> None:
        db.query(CredentialField).filter(
            CredentialField.user_id == credential.user_id,
            CredentialField.credential_id == credential.id,
        ).delete(synchronize_session=False)
        db.delete(credential)
        db.commit()

    def get_credential_detail(self, db: Session, credential: UserCredential) -> Dict[str, object]:
        fields = db.query(CredentialField).filter(
            CredentialField.user_id == credential.user_id,
            CredentialField.credential_id == credential.id,
        ).order_by(CredentialField.id).all()
        return {
            "id": credential.id,
            "label": credential.label,
            "domain": credential.domain,
            "username": credential.username,
            "fields": {field.name: self.decrypt(field.encrypted_value) for field in fields},
        }

    def list_credentials(self, db: Session, user_id: str) -> List[Dict[str, object]]:
        rows = db.query(UserCredential).filter(UserCredential.user_id == user_id).all()
        return [
            {
                "id": row.id,
                "label": row.label,
                "domain": row.domain,
                "username": row.username,
                "password_placeholder": f"{{{{VAULT:{row.label}}}}}",
                "fields": [
                    {"id": field.id, "name": field.name}
                    for field in db.query(CredentialField).filter(
                        CredentialField.user_id == user_id,
                        CredentialField.credential_id == row.id,
                    ).order_by(CredentialField.id).all()
                ],
            }
            for row in rows
        ]

    # ── Retrieval for LLM ─────────────────────────────────────────────────────

    def list_credentials_for_prompt(self, db: Session, user_id: str) -> List[Dict[str, object]]:
        """
        Returns safe metadata for the LLM planner.
        Passwords are NEVER included – only a {{VAULT:label}} placeholder the
        agent can use in its type action parameters.
        """
        rows = db.query(UserCredential).filter(UserCredential.user_id == user_id).all()
        result = []
        for r in rows:
            fields = db.query(CredentialField).filter(
                CredentialField.user_id == user_id,
                CredentialField.credential_id == r.id,
            ).all()
            safe_fields = [{"name": "Login username / email", "token": f"{{{{VAULT_FIELD:{r.id}:0}}}}"}]
            safe_fields.extend(
                {"name": field.name, "token": f"{{{{VAULT_FIELD:{r.id}:{field.id}}}}}"}
                for field in fields
            )
            result.append({
                "label":                r.label,
                "domain":               r.domain,
                "username":             r.username,
                "password_placeholder": f"{{{{VAULT:{r.label}}}}}",
                "fields":               safe_fields,
            })
        return result

    # ── Resolution (browser execution only) ──────────────────────────────────

    def resolve_text(self, db: Session, user_id: str, raw_text: str) -> str:
        """
        Replaces every {{VAULT:label}} token in raw_text with the decrypted password.
        Called only inside StepExecutor, never stored back to the database.
        """
        def _replace_token(match: re.Match) -> str:
            label = match.group(1)
            cred  = (
                db.query(UserCredential)
                .filter(UserCredential.user_id == user_id, UserCredential.label == label)
                .first()
            )
            if not cred:
                raise ValueError(f"Credential '{label}' not found in vault for this user.")
            return self.decrypt(cred.encrypted_password)

        resolved = VAULT_TOKEN_PATTERN.sub(_replace_token, raw_text)

        def _replace_field_token(match: re.Match) -> str:
            credential_id, field_id = int(match.group(1)), int(match.group(2))
            credential = db.query(UserCredential).filter(
                UserCredential.user_id == user_id,
                UserCredential.id == credential_id,
            ).first()
            if not credential:
                raise ValueError("The selected vault profile was not found for this user.")
            if field_id == 0:
                return credential.username
            field = db.query(CredentialField).filter(
                CredentialField.user_id == user_id,
                CredentialField.credential_id == credential_id,
                CredentialField.id == field_id,
            ).first()
            if not field:
                raise ValueError("The selected profile field was not found in the vault.")
            return self.decrypt(field.encrypted_value)

        resolved = VAULT_FIELD_TOKEN_PATTERN.sub(_replace_field_token, resolved)
        if "{{VAULT:" in resolved or "{{VAULT_FIELD:" in resolved:
            raise ValueError("A vault credential token could not be resolved. Check the saved credential label.")
        return resolved

    @staticmethod
    def mask_sensitive_text(text: str) -> str:
        """
        Replaces {{VAULT:label}} tokens with '********' for safe logging.
        Used to sanitize params before saving them to the steps_history in the DB.
        """
        text = VAULT_TOKEN_PATTERN.sub("********", text)
        return VAULT_FIELD_TOKEN_PATTERN.sub("********", text)
