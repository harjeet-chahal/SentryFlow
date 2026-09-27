from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


class UserBase(BaseModel):
    username: str
    email: EmailStr


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    # Validated on the way in, not on the way out: an address stored before
    # a validator change must not turn every read of the account into a 500.
    email: str
    id: str
    is_active: bool
    is_admin: bool = False
    created_at: datetime
    
    class Config:
        orm_mode = True


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class RefreshRequest(BaseModel):
    refresh_token: str


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
