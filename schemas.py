"""
Database Schemas for Youth Founder Network

Each Pydantic model represents a collection in MongoDB.
Collection name is the lowercase of the class name.
"""

from pydantic import BaseModel, Field, HttpUrl, EmailStr
from typing import Optional, List, Literal

# Core profiles
class Profile(BaseModel):
    name: str = Field(..., description="Display name")
    email: EmailStr = Field(..., description="Email address")
    age: int = Field(..., ge=15, le=25, description="Age (15-25)")
    role: Literal["founder", "investor"] = Field(..., description="User type")
    bio: Optional[str] = Field("", description="Short bio")
    interests: List[str] = Field(default_factory=list, description="Topics of interest")
    avatar_url: Optional[HttpUrl] = Field(None, description="Avatar image URL")
    location: Optional[str] = None

# Lightweight post object
class Post(BaseModel):
    user_id: str = Field(..., description="Author id")
    content: str = Field(..., min_length=1, max_length=500)
    tags: List[str] = Field(default_factory=list)

# Live talk/collab rooms
class Room(BaseModel):
    title: str
    topic: str
    description: Optional[str] = ""
    host_id: str
    is_live: bool = True
    cover_url: Optional[HttpUrl] = None
