"""Shared enumerations. String-valued so they serialize cleanly to JSON/DB."""
from enum import Enum


class ContentType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    MIXED = "mixed"


class TaskStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    GENERATED = "generated"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    """Content lifecycle (design doc §5.2):

    DRAFT -> REVIEW -> APPROVED -> QUEUED -> PUBLISHING -> PUBLISHED
                          |
                       REJECTED -> (back to DRAFT)
    """

    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    QUEUED = "queued"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"
