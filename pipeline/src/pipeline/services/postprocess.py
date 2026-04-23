from __future__ import annotations

import html
import re
from uuid import uuid4

from pipeline.config import PipelineSettings
from pipeline.models import CanonicalTask, PrioritizedTaskCard, StructuredLlmOutput, TaskStatus
from pipeline.utils.tags import synthesize_task_tags

SUMMARY_ACTION_HINTS = {
    "submit",
    "submission",
    "complete",
    "review",
    "attend",
    "register",
    "reply",
    "confirm",
    "bring",
    "prepare",
    "join",
    "upload",
    "collect",
    "deadline",
    "due",
    "tonight",
    "tomorrow",
    "tmr",
    "interview",
    "meeting",
    "quiz",
    "assignment",
    "project",
}
SUMMARY_NOISE_HINTS = {
    "posted",
    "shared",
    "wrote",
    "sent",
    "gmail",
    "google classroom",
    "canvas",
    "blackboard",
    "if you don't want to receive",
    "unsubscribe",
    "view in browser",
}


class PostProcessor:
    def __init__(self, settings: PipelineSettings) -> None:
        self.settings = settings

    def build_task_card(
        self,
        *,
        run_id: str,
        task: CanonicalTask,
        llm_output: StructuredLlmOutput,
        profile_version: int,
        available_tags: list[str] | None = None,
    ) -> PrioritizedTaskCard:
        task_title = self._build_task_title(task)
        task_description = self._build_task_description(task, task_title=task_title)
        task_tags = synthesize_task_tags(
            task_type=task.task_type,
            text_parts=[
                task_title,
                task_description,
                task.representative_subject,
                task.representative_body_excerpt,
                task.representative_snippet,
                task.representative_sender_display,
                task.topic_entity.entity_name,
            ],
            score_reasons=task.score_reasons,
            manual_tags=task.manual_tags,
            llm_tags=llm_output.tags,
            available_tags=available_tags,
            max_count=3,
        )
        return PrioritizedTaskCard(
            task_id=uuid4().hex,
            canonical_task_id=task.canonical_task_id,
            user_id=task.user_id,
            run_id=run_id,
            status=TaskStatus.PENDING_REVIEW,
            origin=task.origin,
            task_type=task.task_type,
            entity_key=task.topic_entity.entity_key,
            priority_tier=llm_output.priority_tier,
            suggested_priority_tier=llm_output.priority_tier,
            effective_priority_tier=llm_output.priority_tier,
            applied_priority_delta=0,
            action_window=llm_output.action_window,
            rationale=llm_output.rationale,
            confidence=llm_output.confidence,
            needs_user_review=llm_output.confidence < self.settings.profile_confidence_threshold,
            deadline_at_iso=task.deadline_at.isoformat() if task.deadline_at else None,
            deadline_hours=task.deadline_hours,
            platforms_seen=task.platforms_seen,
            profile_adjustment_made=llm_output.profile_adjustment_made,
            adjustment_reason=llm_output.adjustment_reason,
            evidence_source_ids=task.source_ids,
            task_title=task_title,
            task_description=task_description,
            source_subject=self._clean_text(task.representative_subject),
            source_snippet=self._select_best_preview(task),
            source_sender=self._clean_text(task.representative_sender_display),
            source_timestamp_iso=task.representative_timestamp.isoformat() if task.representative_timestamp else None,
            entity_name=task.topic_entity.entity_name,
            entity_type=task.topic_entity.entity_type,
            score_reasons=task.score_reasons,
            profile_version=profile_version,
            prompt_version=self.settings.llm_prompt_version,
            schema_version_ref=self.settings.llm_schema_version,
            sender_ids=task.sender_ids,
            tags=task_tags,
        )

    def _build_task_title(self, task: CanonicalTask) -> str:
        subject = self._clean_text(task.representative_subject)
        preview = self._select_best_preview(task)
        entity_name = self._clean_text(task.topic_entity.entity_name)

        if subject and subject.lower() != "(no subject)" and not self._is_weak_title(subject):
            if preview and not self._is_duplicate_content(subject, preview) and self._has_key_detail(preview):
                detail = self._compress_preview(preview, limit=70)
                return self._trim_text(f"{subject} - {detail}", limit=120) or subject
            return self._trim_text(subject, limit=120) or subject

        if preview:
            return self._trim_text(preview, limit=120) or preview

        if subject and subject.lower() != "(no subject)":
            return self._trim_text(subject, limit=120) or subject

        return self._build_synthetic_title(task, entity_name)

    def _build_task_description(self, task: CanonicalTask, *, task_title: str) -> str | None:
        summary = self._build_extractive_summary(task, task_title=task_title)
        if summary:
            return summary

        entity_name = self._clean_text(task.topic_entity.entity_name)
        if entity_name and entity_name.lower() not in task_title.lower():
            return f"Related to {entity_name}."

        if task.score_reasons:
            summary = self._trim_text(", ".join(task.score_reasons), limit=160)
            return f"Signals: {summary}."

        return None

    def _clean_text(self, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = html.unescape(value)
        cleaned = re.sub(r"[\u034f\u200b-\u200f\u202a-\u202e]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" \n\r\t-:")
        return cleaned or None

    def _trim_text(self, value: str | None, *, limit: int) -> str | None:
        if value is None or len(value) <= limit:
            return value
        trimmed = value[: limit - 3].rstrip()
        boundary = trimmed.rfind(" ")
        if boundary >= int((limit - 3) * 0.55):
            trimmed = trimmed[:boundary].rstrip(" ,;:-")
        return trimmed + "..."

    def _build_extractive_summary(self, task: CanonicalTask, *, task_title: str) -> str | None:
        candidate_summaries: list[str] = []
        for preview in self._preview_candidates(task):
            summary = self._summarize_preview(preview, task_title=task_title)
            if summary and summary not in candidate_summaries:
                candidate_summaries.append(summary)

        if not candidate_summaries:
            preview = self._select_best_preview(task)
            compressed = self._compress_preview(preview, limit=180) if preview else None
            if compressed:
                candidate_summaries.append(compressed)

        ranked = sorted(
            candidate_summaries,
            key=lambda text: self._summary_score(text, task_title=task_title),
            reverse=True,
        )
        for summary in ranked:
            if not self._is_duplicate_content(task_title, summary):
                return self._trim_text(summary, limit=180)
        return self._trim_text(ranked[0], limit=180) if ranked else None

    def _summarize_preview(self, text: str, *, task_title: str) -> str | None:
        fragments = self._extract_summary_fragments(text)
        if not fragments:
            return None

        ranked = sorted(fragments, key=self._summary_fragment_score, reverse=True)
        selected: list[str] = []
        for fragment in ranked:
            if self._is_duplicate_content(task_title, fragment) and ranked[0] != fragment:
                continue
            if selected and (
                self._is_duplicate_content(selected[0], fragment)
                or not self._fragments_are_complementary(selected[0], fragment)
            ):
                continue
            if selected and len(f"{selected[0]} {fragment}") > 180:
                continue
            selected.append(fragment)
            if len(selected) == 2:
                break

        if not selected:
            return None

        summary = " ".join(self._ensure_terminal_punctuation(fragment) for fragment in selected).strip()
        return re.sub(r"\s+", " ", summary).strip()

    def _extract_summary_fragments(self, text: str) -> list[str]:
        normalized = self._clean_text(text)
        if not normalized:
            return []

        normalized = re.sub(r"\s+\|\s+", ". ", normalized)
        normalized = re.sub(r"\s+-\s+", ". ", normalized)
        raw_fragments = re.split(r"(?<=[.!?])\s+", normalized)

        candidates: list[str] = []
        for fragment in raw_fragments:
            for variant in self._summary_fragment_variants(fragment):
                cleaned = self._clean_summary_fragment(variant)
                if cleaned and cleaned not in candidates and not self._is_noise_fragment(cleaned):
                    candidates.append(cleaned)
        return candidates

    def _summary_fragment_variants(self, fragment: str) -> list[str]:
        variants = [fragment]
        if ":" in fragment:
            _, right = fragment.split(":", 1)
            if right.strip():
                variants.insert(0, right.strip())
        return variants

    def _clean_summary_fragment(self, value: str | None) -> str | None:
        cleaned = self._clean_text(value)
        if not cleaned:
            return None
        cleaned = re.sub(r"^(hi|dear)\s+[^,]{0,80},\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"^[^.]{0,120}\b(posted|shared|sent|wrote|invited you|reminded you)\b[^:]*:\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"^[^.]{0,120}\b(homework for week \d+)\.?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" \n\r\t-:")
        if not cleaned or len(cleaned.split()) < 4:
            return None
        return cleaned

    def _is_noise_fragment(self, text: str) -> bool:
        lowered = text.lower()
        if any(hint in lowered for hint in SUMMARY_NOISE_HINTS):
            return True
        if "http" in lowered or "<" in text:
            return True
        if re.search(r"\b(invited you|posted|shared|sent|wrote)\b", lowered):
            has_timing_detail = bool(
                re.search(
                    r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b|\b(mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday|jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|today|tomorrow|tmr|tonight)\b",
                    lowered,
                )
            )
            has_action_detail = any(
                keyword in lowered
                for keyword in {"submit", "complete", "review", "register", "reply", "confirm", "bring", "prepare"}
            )
            if not has_timing_detail and not has_action_detail:
                return True
        return False

    def _summary_fragment_score(self, text: str) -> tuple[int, int]:
        lowered = text.lower()
        score = 0
        if self._has_key_detail(text):
            score += 4
        if any(keyword in lowered for keyword in SUMMARY_ACTION_HINTS):
            score += 3
        if re.search(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b", lowered):
            score += 2
        if re.search(
            r"\b(mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday|jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b",
            lowered,
        ):
            score += 2
        word_count = len(text.split())
        if 6 <= word_count <= 24:
            score += 2
        elif 4 <= word_count <= 32:
            score += 1
        if any(noise in lowered for noise in SUMMARY_NOISE_HINTS):
            score -= 3
        return (score, min(len(text), 180))

    def _summary_score(self, text: str, *, task_title: str) -> tuple[int, int]:
        base_score = self._summary_fragment_score(text)
        penalty = -2 if self._is_duplicate_content(task_title, text) else 0
        return (base_score[0] + penalty, base_score[1])

    def _fragments_are_complementary(self, left: str, right: str) -> bool:
        if self._is_duplicate_content(left, right):
            return False
        left_words = {word for word in re.findall(r"[a-z0-9]+", left.lower()) if len(word) > 2}
        right_words = {word for word in re.findall(r"[a-z0-9]+", right.lower()) if len(word) > 2}
        overlap = len(left_words & right_words) / min(len(left_words), len(right_words)) if left_words and right_words else 0
        if overlap >= 0.6:
            return False
        right_has_extra_detail = self._has_key_detail(right) or bool(
            re.search(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b", right.lower())
        )
        return right_has_extra_detail

    def _ensure_terminal_punctuation(self, text: str) -> str:
        if text.endswith((".", "!", "?")):
            return text
        return f"{text}."

    def _is_weak_title(self, value: str) -> bool:
        words = value.split()
        if len(words) <= 2:
            return True
        lowered = value.lower()
        if lowered.startswith(("re:", "fw:", "fwd:")):
            return True
        if lowered in {"important", "action required", "reminder", "notification"}:
            return True
        if lowered.startswith(("action required", "usage reached", "security alert")):
            return True
        if len(words) == 3 and not self._has_key_detail(value):
            return True
        if words[-1].lower() in {"your", "the", "a", "an", "of", "for", "to", "with"}:
            return True
        return False

    def _select_best_preview(self, task: CanonicalTask) -> str | None:
        body_preview = self._clean_text(task.representative_body_excerpt)
        snippet_preview = self._clean_text(task.representative_snippet)

        if body_preview and snippet_preview:
            body_score = self._preview_score(body_preview)
            snippet_score = self._preview_score(snippet_preview)
            if body_score >= snippet_score or self._ends_cleanly(body_preview):
                return body_preview
            return snippet_preview

        ranked = self._preview_candidates(task)
        if not ranked:
            return None
        ranked.sort(key=self._preview_score, reverse=True)
        return ranked[0]

    def _select_alternate_preview(self, task: CanonicalTask, *, primary: str | None) -> str | None:
        candidates = self._preview_candidates(task)
        if not candidates:
            return None
        ranked = sorted(candidates, key=self._preview_score, reverse=True)
        for candidate in ranked:
            if primary is None or candidate != primary:
                return candidate
        return None

    def _preview_candidates(self, task: CanonicalTask) -> list[str]:
        candidates: list[str] = []
        for candidate in [task.representative_body_excerpt, task.representative_snippet]:
            cleaned = self._clean_text(candidate)
            if cleaned and cleaned not in candidates:
                candidates.append(cleaned)
        return candidates

    def _preview_score(self, text: str) -> tuple[int, int]:
        score = 0
        lowered = text.lower()
        if self._has_key_detail(text):
            score += 3
        if any(keyword in lowered for keyword in {"submit", "review", "collect", "attend", "register", "complete"}):
            score += 2
        if any(keyword in lowered for keyword in {"due", "deadline", "tonight", "tomorrow", "tmr", "by "}):
            score += 2
        if self._ends_cleanly(text):
            score += 2
        if "http" in lowered or "<" in text:
            score -= 2
        return (score, min(len(text), 260))

    def _has_key_detail(self, text: str) -> bool:
        lowered = text.lower()
        keywords = {
            "submit",
            "submission",
            "deadline",
            "due",
            "by ",
            "tonight",
            "tomorrow",
            "tmr",
            "review",
            "collect",
            "attend",
            "register",
            "meeting",
            "interview",
            "quiz",
            "assignment",
            "project",
        }
        return any(keyword in lowered for keyword in keywords)

    def _compress_preview(self, text: str, *, limit: int) -> str:
        first_clause = re.split(r"(?<=[.!?])\s+| - | \| ", text, maxsplit=1)[0]
        return self._trim_text(first_clause, limit=limit) or text

    def _ends_cleanly(self, text: str) -> bool:
        return text.endswith((".", "!", "?", "\"", "”", ")"))

    def _is_duplicate_content(self, left: str, right: str) -> bool:
        left_words = {word for word in re.findall(r"[a-z0-9]+", left.lower()) if len(word) > 2}
        right_words = {word for word in re.findall(r"[a-z0-9]+", right.lower()) if len(word) > 2}
        if not left_words or not right_words:
            return left.lower() == right.lower()
        overlap = len(left_words & right_words) / min(len(left_words), len(right_words))
        return overlap >= 0.7

    def _build_synthetic_title(self, task: CanonicalTask, entity_name: str | None) -> str:
        kind = {
            "submission": "Submission",
            "meeting": "Meeting",
            "reading": "Reading",
            "admin": "Task",
            "social": "Message",
        }.get(task.task_type.value, "Task")

        if entity_name:
            return f"{kind} related to {entity_name}"
        return kind
