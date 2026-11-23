import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database.database import Base
from app.security.credential_vault import CredentialVault
from app.security.approval_manager import ApprovalManager


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_credential_vault_encryption_and_masking(db_session):
    key = Fernet.generate_key().decode()
    vault = CredentialVault(encryption_key=key)

    vault.store_credential(
        db=db_session,
        user_id="user_123",
        label="portal_pass",
        domain="example.com",
        username="tejasvi@example.com",
        password="SuperSecretPassword!99",
    )

    # Prompt list must NEVER contain the raw password
    prompt_creds = vault.list_credentials_for_prompt(db_session, "user_123")
    assert len(prompt_creds) == 1
    assert prompt_creds[0]["password_placeholder"] == "{{VAULT:portal_pass}}"
    assert "SuperSecretPassword!99" not in str(prompt_creds)

    # Vault resolves placeholder accurately for Playwright
    resolved = vault.resolve_text(db_session, "user_123", "{{VAULT:portal_pass}}")
    assert resolved == "SuperSecretPassword!99"


def test_approval_gate_blocks_sensitive_actions():
    gate = ApprovalManager()

    assert gate.requires_approval("navigate", {"url": "https://example.com"}) is False
    assert gate.requires_approval("click", {"selector": "button[type='submit']"}) is True
    assert gate.requires_approval("type", {"selector": "#password", "text": "{{VAULT:portal_pass}}"}) is True
    assert gate.requires_approval("payment", {"amount": 500}) is True

    gate.request_approval("run_1", 3, {"action": "click", "selector": "#pay-now"}, "Payment action")
    assert gate.get_pending("run_1")["status"] == "pending"

    resolved = gate.resolve("run_1", approved=True)
    assert resolved["status"] == "approved"