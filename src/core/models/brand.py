"""Brand — the user's niche/domain of activity (§3.2).

Guides the Researcher Agent's hot-topic discovery: keywords are the search
queries, niche is the fallback query and tone anchor.
"""
import uuid
from datetime import datetime
from typing import List

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class Brand(SQLModel, table=True):
    __tablename__ = "brand"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    name: str
    niche: str  # e.g. "tech", "entertainment", "fitness"
    keywords: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    tone: str = ""  # optional style guidance for the writer
    # Autopilot: platforms to post to, and whether the brand runs fully
    # autonomously (topic discovery + auto-approval + scheduled publishing).
    platforms: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    autopilot: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
