from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


class Track(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["navidrome", "youtube", "authorized_http"]
    source_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=300)
    artist: str = Field(min_length=1, max_length=300)
    album: str = Field(default="", max_length=300)
    duration: float | None = Field(default=None, gt=0, le=86400)
    recording_mbid: UUID | None = None
    artist_mbids: list[UUID] = Field(default_factory=list, max_length=20)
    isrc: str | None = Field(default=None, pattern=r"^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$")


class PlaylistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    track: Track


class PlaylistWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=150)
    revision: int = Field(ge=0)
    items: list[PlaylistItem] = Field(default_factory=list, max_length=500)


def owner(session: dict) -> str:
    # Names can be renamed/reused in Navidrome. New private data uses native ID.
    value = session.get("user_id")
    if not value:
        raise HTTPException(409, "sign in again to resolve your Navidrome identity")
    return str(value)
