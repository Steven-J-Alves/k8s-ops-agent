from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import declarative_base
from pydantic import BaseModel

Base = declarative_base()


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    namespace = Column(String, index=True, nullable=False)
    resource = Column(String, nullable=False)
    event_reason = Column(String, nullable=False)
    event_message = Column(Text, nullable=False)
    status = Column(String, default="analyzing", nullable=False)
    analysis = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class IncidentResponse(BaseModel):
    id: int
    namespace: str
    resource: str
    event_reason: str
    event_message: str
    status: str
    analysis: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}
