from enum import Enum


class Platform(str, Enum):
    GMAIL = "gmail"
    OUTLOOK = "outlook"
    TEAMS = "teams"
    MANUAL = "manual"


class TaskOrigin(str, Enum):
    EMAIL = "email"
    MANUAL = "manual"


class TaskType(str, Enum):
    SUBMISSION = "submission"
    MEETING = "meeting"
    READING = "reading"
    ADMIN = "admin"
    SOCIAL = "social"


class PriorityTier(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class TaskStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMPLETED = "completed"
    DELETED = "deleted"


class ActionWindow(str, Enum):
    NOW = "NOW"
    TODAY = "TODAY"
    THIS_WEEK = "THIS_WEEK"
    DEFER = "DEFER"


class SenderRole(str, Enum):
    LECTURER = "lecturer"
    PEER = "peer"
    INSTITUTION = "institution"
    ADMIN = "admin"
    GROUP = "group"
    UNKNOWN = "unknown"


class EntityType(str, Enum):
    MODULE = "module"
    CCA = "cca"
    EVENT = "event"
    TOPIC = "topic"
    PLATFORM = "platform"


class FeedbackAction(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    WRONG_PRIORITY = "WRONG_PRIORITY"
    COMPLETED = "COMPLETED"
    DELETE = "DELETE"


class FeedbackDirection(str, Enum):
    TOO_HIGH = "too_high"
    TOO_LOW = "too_low"
