from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from dateparser.search import search_dates

from pipeline.models import Platform, RawMessage, SenderRole, TaskSignal, TaskType, TopicEntity
from pipeline.models.enums import EntityType
from pipeline.utils.text import normalize_entity_name
from pipeline.utils.time import utc_now_naive

try:
    import spacy as spacy
except ImportError:  # pragma: no cover - optional dependency
    spacy = None


TASK_VERBS = {
    "submit",
    "finish",
    "complete",
    "send",
    "review",
    "attend",
    "prepare",
    "read",
    "do",
    "hand",
}
URGENCY_WORDS = {
    "urgent",
    "asap",
    "immediately",
    "tonight",
    "tmr",
    "tomorrow",
    "due",
    "deadline",
    "by",
}
SUBMISSION_HINTS = {"assignment", "submission", "project", "quiz", "lab", "deliverable"}
MEETING_HINTS = {"meeting", "zoom", "call", "interview", "briefing", "sync"}
READING_HINTS = {"read", "reading", "article", "notes", "slides", "chapter"}
ADMIN_HINTS = {"register", "verify", "form", "payment", "invoice", "confirmation"}
MODULE_PATTERN = re.compile(r"\b[A-Z]{2,3}\d{4}[A-Z]?\b")
CCA_KEYWORDS = {"cca", "welfare", "club", "society", "hall", "rag", "flag", "committee"}
DEADLINE_RELATIVE_TERMS = {"today", "tomorrow", "tmr", "tonight", "next"}
MONTH_OR_WEEKDAY_PATTERN = re.compile(
    r"\b("
    r"jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|"
    r"sep|sept|september|oct|october|nov|november|dec|december|"
    r"mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday"
    r")\b",
    re.IGNORECASE,
)
TIME_PATTERN = re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b", re.IGNORECASE)
PURE_NUMERIC_PATTERN = re.compile(r"^\d+(?::\d+)?$")


class SignalExtractor:
    def __init__(self, *, timezone_fallback: str = "UTC") -> None:
        self.timezone_fallback = timezone_fallback
        self._nlp = self._load_nlp()

    def _load_nlp(self):  # pragma: no cover - exercised indirectly
        if spacy is None:
            return None
        for model_name in ("en_core_web_sm", "en_core_web_md"):
            try:
                return spacy.load(model_name)
            except OSError:
                continue
        return spacy.blank("en")

    def extract(self, message: RawMessage) -> TaskSignal:
        text = self._build_text(message)
        timestamp = self._parse_timestamp(message.timestamp_iso)
        lowercase_text = text.lower()
        doc = self._nlp(text) if self._nlp is not None else None

        task_verbs = self._extract_task_verbs(lowercase_text)
        urgency_terms = self._extract_urgency_terms(lowercase_text)
        deadline_at = self._extract_deadline(text, reference_time=timestamp)
        topic_entity = self._extract_topic_entity(text, message, doc)
        deadline_hours = self._deadline_hours(deadline_at, reference_time=timestamp)
        task_type = self._classify_task_type(lowercase_text, task_verbs, topic_entity)
        has_task = bool(task_verbs or urgency_terms or deadline_at or task_type != TaskType.ADMIN)

        return TaskSignal(
            user_id=message.user_id,
            source_id=message.source_id,
            platform=message.platform,
            timestamp=timestamp,
            sender_id=message.sender_id or message.sender_email,
            sender_role=self._classify_sender(message),
            subject=message.subject,
            snippet=message.snippet,
            body_excerpt=message.body_text[:280] if message.body_text else None,
            task_type=task_type,
            has_task=has_task,
            task_verbs_found=task_verbs,
            urgency_word_count=len(urgency_terms),
            urgency_terms=urgency_terms,
            deadline_hours=deadline_hours,
            deadline_at=deadline_at,
            topic_entity=topic_entity,
            platforms_seen=[message.platform],
        )

    def _build_text(self, message: RawMessage) -> str:
        return "\n".join(part for part in [message.subject, message.snippet, message.body_text] if part)

    def _extract_task_verbs(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-z]+", text)
        return [token for token in tokens if token in TASK_VERBS]

    def _extract_urgency_terms(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-z]+", text)
        return [token for token in tokens if token in URGENCY_WORDS]

    def _extract_deadline(self, text: str, *, reference_time: datetime | None = None) -> datetime | None:
        cleaned_text = self._prepare_text_for_deadline_search(text)
        base_time = reference_time or utc_now_naive()
        matches = search_dates(
            cleaned_text,
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": False,
                "TIMEZONE": self.timezone_fallback,
                "RELATIVE_BASE": base_time,
            },
        )
        if not matches:
            return None
        candidates: list[tuple[datetime, str]] = []
        for matched_text, parsed in matches:
            adjusted = self._normalize_deadline_candidate(matched_text, parsed, base_time=base_time)
            if not self._is_acceptable_deadline_match(matched_text, adjusted, base_time=base_time):
                continue
            candidates.append((adjusted, matched_text))
        candidates.sort(key=lambda item: item[0])
        for parsed, _ in candidates:
            if parsed >= base_time:
                return parsed
        return candidates[0][0] if candidates else None

    def _deadline_hours(self, deadline_at: datetime | None, *, reference_time: datetime | None = None) -> float | None:
        if deadline_at is None:
            return None
        delta = deadline_at - (reference_time or utc_now_naive())
        return max(0.0, delta.total_seconds() / 3600)

    def _prepare_text_for_deadline_search(self, text: str) -> str:
        cleaned_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append("")
                continue
            if stripped.startswith(">"):
                continue
            if re.match(r"^on\s+.+wrote:\s*$", stripped, re.IGNORECASE):
                continue
            stripped = re.sub(r"https?://\S+", " ", stripped)
            stripped = re.sub(r"<https?://[^>]+>", " ", stripped)
            cleaned_lines.append(stripped)
        return "\n".join(cleaned_lines)

    def _is_acceptable_deadline_match(
        self,
        matched_text: str,
        parsed: datetime,
        *,
        base_time: datetime,
    ) -> bool:
        candidate = matched_text.strip().lower()
        if not candidate:
            return False
        if "&#" in candidate:
            return False
        if PURE_NUMERIC_PATTERN.fullmatch(candidate):
            return False
        if len(candidate) <= 2:
            return False
        if parsed < base_time:
            return False
        if (parsed - base_time).total_seconds() > 366 * 24 * 3600:
            return False

        contains_relative_term = any(term in candidate for term in DEADLINE_RELATIVE_TERMS)
        has_named_date = MONTH_OR_WEEKDAY_PATTERN.search(candidate) is not None
        has_time = TIME_PATTERN.search(candidate) is not None

        return contains_relative_term or has_named_date or has_time

    def _normalize_deadline_candidate(
        self,
        matched_text: str,
        parsed: datetime,
        *,
        base_time: datetime,
    ) -> datetime:
        candidate = matched_text.strip().lower()
        has_explicit_year = re.search(r"\b\d{4}\b", candidate) is not None
        if has_explicit_year:
            return parsed
        if (parsed - base_time).total_seconds() > 180 * 24 * 3600:
            try:
                return parsed.replace(year=base_time.year)
            except ValueError:
                return parsed
        return parsed

    def _extract_topic_entity(self, raw_text: str, message: RawMessage, doc: Any) -> TopicEntity:
        module_match = MODULE_PATTERN.search(raw_text)
        if module_match:
            name = module_match.group()
            return TopicEntity(entity_name=name, entity_type=EntityType.MODULE, entity_key=normalize_entity_name(name))

        if doc is not None:
            for ent in getattr(doc, "ents", []):
                if ent.label_ in {"ORG", "EVENT"}:
                    entity_type = (
                        EntityType.CCA
                        if any(keyword in ent.text.lower() for keyword in CCA_KEYWORDS)
                        else EntityType.EVENT
                    )
                    return TopicEntity(
                        entity_name=ent.text.strip(),
                        entity_type=entity_type,
                        entity_key=normalize_entity_name(ent.text),
                    )

        lower_text = raw_text.lower()
        if doc is not None:
            for keyword in CCA_KEYWORDS:
                if keyword in lower_text:
                    for chunk in self._noun_chunks(doc):
                        if keyword in chunk.text.lower():
                            return TopicEntity(
                                entity_name=chunk.text.strip(),
                                entity_type=EntityType.CCA,
                                entity_key=normalize_entity_name(chunk.text),
                            )

        fallback = self._fallback_topic(raw_text, doc)
        if fallback:
            return TopicEntity(
                entity_name=fallback,
                entity_type=EntityType.TOPIC,
                entity_key=normalize_entity_name(fallback),
            )

        return TopicEntity(
            entity_name=message.platform.value,
            entity_type=EntityType.PLATFORM,
            entity_key=normalize_entity_name(message.platform.value),
        )

    def _fallback_topic(self, raw_text: str, doc: Any) -> str | None:
        if doc is not None:
            noun_chunks = [chunk.text.strip() for chunk in self._noun_chunks(doc) if chunk.text.strip()]
            if noun_chunks:
                return noun_chunks[0]
        tokens = [token for token in re.findall(r"[A-Za-z0-9]+", raw_text) if len(token) > 3]
        return " ".join(tokens[:3]) if tokens else None

    def _noun_chunks(self, doc: Any) -> list[Any]:
        try:
            return list(doc.noun_chunks)
        except Exception:
            return []

    def _classify_sender(self, message: RawMessage) -> SenderRole:
        sender_domain = (message.sender_domain or "").lower()
        sender_display = (message.sender_display or "").lower()
        sender_email = (message.sender_email or "").lower()
        text = " ".join([sender_domain, sender_display, sender_email]).strip()

        if any(token in text for token in ("prof", "lecturer", "edu", "faculty", "teacher")):
            return SenderRole.LECTURER
        if any(token in text for token in ("group", "channel", "team", "committee")):
            return SenderRole.GROUP
        if any(token in text for token in ("admin", "office", "registrar", "support")):
            return SenderRole.ADMIN
        if any(token in text for token in ("noreply", "outlook", "microsoft", "google", "canvas", "nus")):
            return SenderRole.INSTITUTION
        if text:
            return SenderRole.PEER
        return SenderRole.UNKNOWN

    def _classify_task_type(self, text: str, task_verbs: list[str], entity: TopicEntity) -> TaskType:
        if entity.entity_type == EntityType.MODULE and any(term in text for term in SUBMISSION_HINTS):
            return TaskType.SUBMISSION
        if any(term in text for term in SUBMISSION_HINTS) or any(verb in task_verbs for verb in {"submit", "complete"}):
            return TaskType.SUBMISSION
        if any(term in text for term in MEETING_HINTS) or "attend" in task_verbs:
            return TaskType.MEETING
        if any(term in text for term in READING_HINTS) or "read" in task_verbs:
            return TaskType.READING
        if any(term in text for term in ADMIN_HINTS):
            return TaskType.ADMIN
        return TaskType.SOCIAL if entity.entity_type in {EntityType.CCA, EntityType.EVENT, EntityType.TOPIC} else TaskType.ADMIN

    def _parse_timestamp(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
