from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, JSON, UniqueConstraint
from app.database.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class UserCredential(Base):
    __tablename__ = "user_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(128), index=True, nullable=False)
    label = Column(String(100), nullable=False)  # e.g., "amazon_login"
    domain = Column(String(255), nullable=False)  # e.g., "amazon.in"
    username = Column(String(255), nullable=False)
    encrypted_password = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class CredentialField(Base):
    __tablename__ = "credential_fields"
    __table_args__ = (UniqueConstraint("credential_id", "name_key", name="uq_credential_field_name"),)

    id = Column(Integer, primary_key=True, index=True)
    credential_id = Column(Integer, ForeignKey("user_credentials.id"), index=True, nullable=False)
    user_id = Column(String(128), index=True, nullable=False)
    name = Column(String(100), nullable=False)
    name_key = Column(String(100), nullable=False)
    encrypted_value = Column(Text, nullable=False)


class ExecutionRun(Base):
    __tablename__ = "execution_runs"

    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(String(128), index=True, nullable=False)
    task = Column(Text, nullable=False)
    status = Column(String(32), default="running")  # running, awaiting_approval, completed, failed, rejected
    plan = Column(JSON, default=list)
    steps_log = Column(JSON, default=list)
    extracted_data = Column(JSON, default=dict)
    final_summary = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SavedWorkflow(Base):
    __tablename__ = "saved_workflows"

    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(String(128), index=True, nullable=False)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    task_prompt = Column(Text, nullable=False)
    steps = Column(JSON, default=list)
    schedule_cron = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
