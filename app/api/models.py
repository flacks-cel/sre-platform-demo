import uuid
from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class JobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, examples=["resize-image"])
    payload: dict = Field(default_factory=dict, examples=[{"file": "photo.jpg"}])


class Job(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    payload: dict
    status: JobStatus = JobStatus.pending

    model_config = {"use_enum_values": True}
