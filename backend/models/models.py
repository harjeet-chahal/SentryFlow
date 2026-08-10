from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, index=True)
    username = Column(String(50), unique=True, index=True)
    hashed_password = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    api_keys = relationship("ApiKey", back_populates="user")
    rate_limits = relationship("RateLimit", back_populates="user")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    key = Column(String(64), unique=True, index=True)
    name = Column(String(100))
    user_id = Column(String(36), ForeignKey("users.id"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="api_keys")


class RateLimit(Base):
    __tablename__ = "rate_limits"

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"))
    endpoint = Column(String(255))
    requests_per_minute = Column(Integer, default=60)  # Default: 60 requests per minute
    burst_capacity = Column(Integer, default=10)  # For token bucket algorithm
    algorithm = Column(String(20), default="sliding_window")  # sliding_window or token_bucket
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="rate_limits")


class ApiUsage(Base):
    __tablename__ = "api_usage"

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"))
    endpoint = Column(String(255))
    status_code = Column(Integer)
    response_time = Column(Integer)  # in milliseconds
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # No relationship back to User to avoid performance issues with large tables