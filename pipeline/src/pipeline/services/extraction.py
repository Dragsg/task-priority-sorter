from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from dateparser.search import search_dates

from pipeline.models import Platform, RawMessage, SenderRole, TaskOrigin, TaskSignal, TaskType, TopicEntity
from pipeline.models.enums import EntityType
from pipeline.utils.tags import dedupe_tags
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
COMMERCIAL_DOMAINS = {
    "shopee.com",
    "lazada.com",
    "grab.com",
    "foodpanda.com",
    "netflix.com",
    "spotify.com",
    "amazon.com",
    "booking.com",
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "openai.com",
    "anthropic.com",
}
GMAIL_HARD_DISCARD_LABELS = {
    "CATEGORY_PROMOTIONS",
    "CATEGORY_SOCIAL",
    "CATEGORY_FORUMS",
    "SPAM",
    "TRASH",
}
GMAIL_SOFT_BULK_LABELS = {
    "CATEGORY_UPDATES",
}
IRRELEVANT_SUBJECT_PATTERNS = {
    "security alert",
    "usage reached",
    "storage is almost full",
    "storage usage",
    "newsletter",
    "promotion",
    "offer",
    "sale",
    "shipped",
    "delivered",
    "order confirmation",
    "receipt",
    "statement",
    "invoice",
    "payment received",
    "subscription",
    "verify your email",
    "welcome to",
    "thanks for signing up",
}
NEWSLETTER_HINT_PATTERNS = {
    "newsletter",
    "digest",
    "roundup",
    "morning brew",
    "daily",
    "weekly",
    "edition",
    "trial",
    "unsubscribe",
    "view online",
}
BULK_PRECEDENCE_VALUES = {"bulk", "list", "junk"}
TRUSTED_NEWSLETTER_OVERRIDE_ROLES = {
    SenderRole.LECTURER,
    SenderRole.ADMIN,
    SenderRole.INSTITUTION,
}
MODULE_PATTERN = re.compile(r"\b[A-Z]{2,3}\d{4}[A-Z]?\b")
CCA_KEYWORDS = {"cca", "welfare", "club", "society", "hall", "rag", "flag", "committee"}
DEADLINE_RELATIVE_TERMS = {"today", "tomorrow", "tmr", "tonight", "next"}
PREVIEW_SKIP_PHRASES = {
    "if you don't want to receive emails",
    "unsubscribe",
    "google inc.",
    "mountain view",
    "view in browser",
    "reply directly to this email",
    "do not reply to this email",
    "this message was sent",
    "with regards",
    "best regards",
    "head of department",
    "academic staff",
    "teacher in-charge",
    "special projects",
    "apple distinguished educator",
    "google certified innovator",
    "school of science and technology",
    "confidentiality:",
    "technology drive",
    "website",
    "facebook",
    "twitter",
    "1600 amphitheatre pkwy",
    "amphitheatre parkway",
    "mountain view, ca",
    "mountain view ca",
}
PREVIEW_ACTION_HINTS = {
    "assignment",
    "question",
    "quiz",
    "project",
    "homework",
    "submit",
    "submission",
    "complete",
    "review",
    "collect",
    "attend",
    "register",
    "training",
    "trial",
    "interview",
    "deadline",
    "due",
    "before",
    "by ",
    "invited you",
    "class invitation",
    "join",
    "meeting",
    "lesson",
    "password",
    "login",
    "log in",
    "account",
    "user id",
    "update your email",
}
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
        manual_metadata = self._manual_metadata(message)

        task_verbs = self._extract_task_verbs(lowercase_text)
        urgency_terms = self._extract_urgency_terms(lowercase_text)
        deadline_at = self._manual_deadline(manual_metadata) or self._extract_deadline(text, reference_time=timestamp)
        topic_entity = self._manual_topic_entity(manual_metadata) or self._extract_topic_entity(text, message, doc)
        deadline_hours = self._deadline_hours(deadline_at, reference_time=timestamp)
        task_type = self._manual_task_type(manual_metadata) or self._classify_task_type(lowercase_text, task_verbs, topic_entity)
        sender_role = self._classify_sender(message)
        has_task = True if manual_metadata else not self._should_discard_message(
            message,
            lowercase_text,
            deadline_at=deadline_at,
            sender_role=sender_role,
            task_verbs=task_verbs,
            task_type=task_type,
            topic_entity=topic_entity,
        ) and bool(
            task_verbs
            or urgency_terms
            or deadline_at
            or task_type in {TaskType.SUBMISSION, TaskType.MEETING, TaskType.READING, TaskType.ADMIN}
        )

        return TaskSignal(
            user_id=message.user_id,
            source_id=message.source_id,
            platform=message.platform,
            origin=TaskOrigin.MANUAL if message.platform == Platform.MANUAL else TaskOrigin.EMAIL,
            timestamp=timestamp,
            sender_id=message.sender_id or message.sender_email,
            sender_display=message.sender_display or message.sender_email or message.from_raw,
            sender_role=sender_role,
            subject=message.subject,
            snippet=message.snippet,
            body_excerpt=self._build_body_excerpt(message),
            task_type=task_type,
            has_task=has_task,
            task_verbs_found=task_verbs,
            urgency_word_count=len(urgency_terms),
            urgency_terms=urgency_terms,
            deadline_hours=deadline_hours,
            deadline_at=deadline_at,
            topic_entity=topic_entity,
            platforms_seen=[message.platform],
            manual_tags=self._manual_tags(manual_metadata),
        )

    def _build_text(self, message: RawMessage) -> str:
        return "\n".join(part for part in [message.subject, message.snippet, message.body_text] if part)

    def _build_body_excerpt(self, message: RawMessage) -> str | None:
        body_lines = self._extract_preview_lines(message.body_text)
        if body_lines:
            relevant_indices = [index for index, line in enumerate(body_lines) if self._preview_line_score(line) >= 3]
            start_index = relevant_indices[0] if relevant_indices else 0
            if start_index > 0 and body_lines[start_index].lower().startswith(
                ("due", "please", "submit", "complete", "attend", "join", "bring", "register", "before", "by")
            ):
                start_index -= 1

            preview_parts: list[str] = []
            for line in body_lines[start_index:]:
                candidate = " ".join(preview_parts + [line]).strip()
                if len(candidate) > 360 and preview_parts:
                    break
                preview_parts.append(line)
                if len(preview_parts) >= 3:
                    break
                if len(candidate) >= 220 and self._preview_has_enough_detail(candidate):
                    break

            preview_text = " ".join(preview_parts).strip()
            cleaned_preview = self._clean_preview_fragment(preview_text, limit=360)
            if cleaned_preview:
                if not cleaned_preview.endswith((".", "!", "?", "...")) and self._preview_has_enough_detail(cleaned_preview):
                    cleaned_preview = f"{cleaned_preview}."
                return cleaned_preview

        return self._clean_preview_fragment(message.snippet, limit=280)

    def _extract_preview_lines(self, text: str | None) -> list[str]:
        if not text:
            return []

        cleaned_lines: list[str] = []
        current_parts: list[str] = []
        for raw_line in text.splitlines():
            if not raw_line.strip():
                if current_parts:
                    cleaned_lines.append(" ".join(current_parts).strip())
                    current_parts = []
                continue
            line = self._clean_preview_line(raw_line)
            if not line:
                continue
            lower_line = line.lower()
            if lower_line in {"open", "join", "view details"}:
                if current_parts:
                    cleaned_lines.append(" ".join(current_parts).strip())
                    current_parts = []
                continue
            if any(phrase in lower_line for phrase in PREVIEW_SKIP_PHRASES):
                if current_parts:
                    cleaned_lines.append(" ".join(current_parts).strip())
                    current_parts = []
                continue
            current_parts.append(self._strip_greeting_prefix(line))

        if current_parts:
            cleaned_lines.append(" ".join(current_parts).strip())

        cleaned_lines = [re.sub(r"\s+", " ", line).strip() for line in cleaned_lines if line.strip()]

        if len(cleaned_lines) > 1 and re.match(r"^(hi|dear)\b", cleaned_lines[0], re.IGNORECASE) and len(cleaned_lines[0].split()) <= 4:
            cleaned_lines = cleaned_lines[1:]

        return cleaned_lines

    def _strip_greeting_prefix(self, value: str) -> str:
        return re.sub(r"^(hi|dear)\s+[^,]{0,80},\s*", "", value, flags=re.IGNORECASE)

    def _clean_preview_line(self, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = html.unescape(value)
        if cleaned.lstrip().startswith("[image:"):
            return None
        cleaned = re.sub(r"<https?://[^>]+>", " ", cleaned)
        cleaned = re.sub(r"https?://\S+", " ", cleaned)
        cleaned = re.sub(r"[_*`~]+", " ", cleaned)
        cleaned = re.sub(r"\[[^\]]+\]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" \n\r\t-•|")
        if not cleaned or len(cleaned) < 3:
            return None
        if cleaned.isupper() and len(cleaned.split()) <= 2:
            return None
        return cleaned

    def _preview_line_score(self, text: str) -> int:
        lowered = text.lower()
        score = 0
        if any(hint in lowered for hint in PREVIEW_ACTION_HINTS):
            score += 4
        if any(token in lowered for token in {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}):
            score += 1
        if re.search(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)?\b", lowered):
            score += 1
        if len(text.split()) >= 6:
            score += 1
        if any(phrase in lowered for phrase in PREVIEW_SKIP_PHRASES):
            score -= 5
        return score

    def _preview_has_enough_detail(self, text: str) -> bool:
        lowered = text.lower()
        return any(hint in lowered for hint in PREVIEW_ACTION_HINTS) and len(text.split()) >= 8

    def _clean_preview_fragment(self, value: str | None, *, limit: int) -> str | None:
        if not value:
            return None
        cleaned = html.unescape(value)
        cleaned = re.sub(r"[\u034f\u200b-\u200f\u202a-\u202e]", "", cleaned)
        cleaned = re.sub(r"<https?://[^>]+>", " ", cleaned)
        cleaned = re.sub(r"https?://\S+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" \n\r\t-•|")
        if not cleaned:
            return None
        if len(cleaned) <= limit:
            return cleaned

        window = cleaned[:limit].rstrip()
        punctuation_boundary = max(window.rfind("."), window.rfind("!"), window.rfind("?"))
        if punctuation_boundary >= int(limit * 0.55):
            return window[: punctuation_boundary + 1].rstrip()

        word_boundary = window.rfind(" ")
        if word_boundary >= int(limit * 0.55):
            return window[:word_boundary].rstrip(" ,;:-") + "..."
        return window + "..."

    def _manual_metadata(self, message: RawMessage) -> dict[str, Any] | None:
        extra = getattr(message.provider_metadata, "extra", {}) or {}
        manual = extra.get("manual_task")
        return manual if isinstance(manual, dict) else None

    def _manual_deadline(self, metadata: dict[str, Any] | None) -> datetime | None:
        if not metadata:
            return None
        deadline_value = metadata.get("deadline_iso")
        if not deadline_value:
            return None
        try:
            return datetime.fromisoformat(str(deadline_value).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    def _manual_task_type(self, metadata: dict[str, Any] | None) -> TaskType | None:
        if not metadata:
            return None
        value = metadata.get("task_type")
        try:
            return TaskType(value) if value else None
        except ValueError:
            return None

    def _manual_tags(self, metadata: dict[str, Any] | None) -> list[str]:
        if not metadata:
            return []
        raw_tags = metadata.get("tags")
        if not isinstance(raw_tags, list):
            return []
        return dedupe_tags(raw_tags)

    def _manual_topic_entity(self, metadata: dict[str, Any] | None) -> TopicEntity | None:
        if not metadata:
            return None
        entity_name = (metadata.get("entity_name") or "").strip()
        entity_type_value = metadata.get("entity_type")
        if not entity_name:
            return None
        try:
            entity_type = EntityType(entity_type_value) if entity_type_value else EntityType.TOPIC
        except ValueError:
            entity_type = EntityType.TOPIC
        return TopicEntity(
            entity_name=entity_name,
            entity_type=entity_type,
            entity_key=normalize_entity_name(entity_name),
        )

    def _should_discard_message(
        self,
        message: RawMessage,
        lowercase_text: str,
        *,
        deadline_at: datetime | None,
        sender_role: SenderRole,
        task_verbs: list[str],
        task_type: TaskType,
        topic_entity: TopicEntity,
    ) -> bool:
        sender_domain = (message.sender_domain or "").lower()
        subject = (message.subject or "").lower()
        label_ids = {str(label).upper() for label in (message.label_ids or [])}

        if "SPAM" in label_ids or "TRASH" in label_ids:
            return True

        if label_ids & GMAIL_HARD_DISCARD_LABELS:
            if not self._allows_newsletter_task_override(
                lowercase_text,
                deadline_at=deadline_at,
                sender_role=sender_role,
                task_verbs=task_verbs,
                task_type=task_type,
                topic_entity=topic_entity,
            ):
                return True

        if self._is_likely_newsletter_message(message, lowercase_text, subject, sender_domain, label_ids):
            if not self._allows_newsletter_task_override(
                lowercase_text,
                deadline_at=deadline_at,
                sender_role=sender_role,
                task_verbs=task_verbs,
                task_type=task_type,
                topic_entity=topic_entity,
            ):
                return True

        if deadline_at is not None:
            return False

        if any(domain in sender_domain for domain in COMMERCIAL_DOMAINS):
            return True

        return any(pattern in subject or pattern in lowercase_text for pattern in IRRELEVANT_SUBJECT_PATTERNS)

    def _is_likely_newsletter_message(
        self,
        message: RawMessage,
        lowercase_text: str,
        subject: str,
        sender_domain: str,
        label_ids: set[str],
    ) -> bool:
        if label_ids & GMAIL_SOFT_BULK_LABELS:
            return True
        if any(pattern in subject or pattern in lowercase_text for pattern in NEWSLETTER_HINT_PATTERNS):
            return True
        if any(domain in sender_domain for domain in COMMERCIAL_DOMAINS):
            return True
        return self._has_bulk_mail_headers(message)

    def _has_bulk_mail_headers(self, message: RawMessage) -> bool:
        extra = getattr(message.provider_metadata, "extra", {}) or {}
        precedence = str(extra.get("precedence") or "").strip().lower()
        return bool(
            extra.get("list_unsubscribe")
            or extra.get("list_id")
            or extra.get("mailing_list")
            or precedence in BULK_PRECEDENCE_VALUES
        )

    def _allows_newsletter_task_override(
        self,
        lowercase_text: str,
        *,
        deadline_at: datetime | None,
        sender_role: SenderRole,
        task_verbs: list[str],
        task_type: TaskType,
        topic_entity: TopicEntity,
    ) -> bool:
        if sender_role in TRUSTED_NEWSLETTER_OVERRIDE_ROLES:
            return bool(
                deadline_at is not None
                or topic_entity.entity_type == EntityType.MODULE
                or task_type in {TaskType.SUBMISSION, TaskType.ADMIN, TaskType.MEETING}
                or any(verb in task_verbs for verb in {"submit", "complete", "review", "attend", "register"})
            )

        if topic_entity.entity_type == EntityType.MODULE:
            return bool(
                deadline_at is not None
                or any(verb in task_verbs for verb in {"submit", "complete", "review", "register"})
            )

        if deadline_at is not None and any(
            verb in task_verbs for verb in {"submit", "complete", "review", "attend", "register", "prepare"}
        ):
            return True

        if task_type == TaskType.ADMIN and deadline_at is not None and any(
            term in lowercase_text for term in {"verify", "register", "form", "payment", "invoice", "confirmation"}
        ):
            return True

        return False

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
