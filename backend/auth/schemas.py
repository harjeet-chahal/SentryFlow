from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


class UserBase(BaseModel):
    username: str
    email: EmailStr


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    id: str
    is_active: bool
    created_at: datetime
    
    class Config:
        orm_mode = True


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class ApiKeyBase(BaseModel):
    name: str = Field(..., description="A friendly name for the API key")


class ApiKeyCreate(ApiKeyBase):
    pass


class ApiKeyResponse(ApiKeyBase):
    id: str
    key: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    is_active: bool
    
    class Config:
        orm_mode = True


class RateLimitBase(BaseModel):
    endpoint: str
    requests_per_minute: int = 60
    burst_capacity: int = 10
    algorithm: str = "sliding_window"


class RateLimitCreate(RateLimitBase):
    pass


class RateLimitResponse(RateLimitBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True