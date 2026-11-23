from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Integer, String, Text, JSON
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


class ExecutionRun(Base):
    __tablename__ = "execution_runs"

    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(String(128), index=True, nullable=False)
    task = Column(Text, nullable=False)
    status = Column(String(32), default="running")  # running, awaiting_approval, completed, failed, rejected
    plan = Column(JSON, default=list)
    steps_log = Column(JSON, default=list)
    extracted_data = Column(JSON, default=dict)
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