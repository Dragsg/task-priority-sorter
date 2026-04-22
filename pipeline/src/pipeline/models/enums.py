from enum import Enum


class Platform(str, Enum):
    GMAIL = "gmail"
    OUTLOOK = "outlook"
    TEAMS = "teams"
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
    GOT_IT = "GOT_IT"
    RESCHEDULE = "RESCHEDULE"
    ALREADY_DONE = "ALREADY_DONE"
    WRONG_PRIORITY = "WRONG_PRIORITY"


class FeedbackDirection(str, Enum):
    TOO_HIGH = "too_high"
    TOO_LOW = "too_low"
