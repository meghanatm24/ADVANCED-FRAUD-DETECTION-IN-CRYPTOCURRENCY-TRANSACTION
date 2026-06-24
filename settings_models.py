# settings_models.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base

# Reuse the same Base your app uses.
# If you already have db.Base, import it instead of creating a new one:
# from db import Base
Base = declarative_base()  # <- replace with "from db import Base" if available

class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    # Store hash only
    key_hash = Column(String(128), nullable=False, index=True)
    last_four = Column(String(8), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class UserSettings(Base):
    __tablename__ = "user_settings"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, unique=True)

    # Notification prefs
    email_notifications = Column(Boolean, default=True, nullable=False)
    push_notifications = Column(Boolean, default=True, nullable=False)
    fraud_alerts = Column(Boolean, default=True, nullable=False)
    weekly_reports = Column(Boolean, default=False, nullable=False)

    # “Profile” fields (kept here to avoid needing a User model)
    first_name = Column(String(120), nullable=True)
    last_name = Column(String(120), nullable=True)
    full_name = Column(String(240), nullable=True)
    phone = Column(String(64), nullable=True)

    __table_args__ = (UniqueConstraint('user_id', name='uq_user_settings_user'),)
