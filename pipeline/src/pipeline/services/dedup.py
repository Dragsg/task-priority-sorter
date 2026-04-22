from __future__ import annotations

from uuid import uuid5, NAMESPACE_URL

from pipeline.config import PipelineSettings
from pipeline.models import CanonicalTask, Platform, SenderRole, TaskOrigin, TaskSignal
from pipeline.utils.tags import dedupe_tags

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - optional dependency
    SentenceTransformer = None


class TaskDeduplicator:
    def __init__(self, settings: PipelineSettings) -> None:
        self.settings = settings
        self._embedder = None
        self._model_name = "all-MiniLM-L6-v2"

    def _get_embedder(self):  # pragma: no cover - exercised indirectly
        if self._embedder is not None or SentenceTransformer is None:
            return self._embedder
        try:
            self._embedder = SentenceTransformer(self._model_name)
        except Exception:
            self._embedder = None
        return self._embedder

    def deduplicate(self, signals: list[TaskSignal], *, run_id: str) -> list[CanonicalTask]:
        clusters: list[list[TaskSignal]] = []

        for signal in signals:
            placed = False
            for cluster in clusters:
                if self._should_merge(cluster[0], signal):
                    cluster.append(signal)
                    placed = True
                    break
            if not placed:
                clusters.append([signal])

        return [self._merge_cluster(cluster, run_id=run_id) for cluster in clusters]

    def _should_merge(self, left: TaskSignal, right: TaskSignal) -> bool:
        if left.task_type != right.task_type:
            return False
        if left.topic_entity.entity_key == right.topic_entity.entity_key:
            return self._deadline_compatible(left.deadline_hours, right.deadline_hours)
        similarity = self._phrase_similarity(self._representative_phrase(left), self._representative_phrase(right))
        return similarity >= self.settings.dedup_similarity_threshold and self._deadline_compatible(
            left.deadline_hours,
            right.deadline_hours,
        )

    def _deadline_compatible(self, left: float | None, right: float | None) -> bool:
        if left is None or right is None:
            return True
        return abs(left - right) <= 72

    def _representative_phrase(self, signal: TaskSignal) -> str:
        subject = signal.subject or ""
        return f"{signal.task_type.value} {signal.topic_entity.entity_name} {subject}".strip()

    def _phrase_similarity(self, left: str, right: str) -> float:
        embedder = self._get_embedder()
        if embedder is not None:  # pragma: no cover - optional dependency
            left_embedding, right_embedding = embedder.encode([left, right], normalize_embeddings=True)
            return float(left_embedding @ right_embedding)
        left_tokens = set(left.lower().split())
        right_tokens = set(right.lower().split())
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    def _merge_cluster(self, cluster: list[TaskSignal], *, run_id: str) -> CanonicalTask:
        first = cluster[0]
        representative = self._select_representative_signal(cluster)
        deadline_at_values = [signal.deadline_at for signal in cluster if signal.deadline_at is not None]
        deadline_values = [signal.deadline_hours for signal in cluster if signal.deadline_hours is not None]
        sender_roles = list({signal.sender_role for signal in cluster})
        sender_ids = list({signal.sender_id for signal in cluster if signal.sender_id})
        platforms_seen = list({platform for signal in cluster for platform in signal.platforms_seen})
        representative_subject = representative.subject
        representative_snippet = representative.snippet
        representative_body_excerpt = representative.body_excerpt
        canonical_id_seed = (
            f"{first.user_id}:{first.topic_entity.entity_key}:{first.task_type.value}:{representative_subject or ''}"
        )
        canonical_task_id = uuid5(NAMESPACE_URL, canonical_id_seed).hex

        return CanonicalTask(
            canonical_task_id=canonical_task_id,
            user_id=first.user_id,
            run_id=run_id,
            origin=TaskOrigin.MANUAL if any(signal.origin == TaskOrigin.MANUAL for signal in cluster) else TaskOrigin.EMAIL,
            task_type=first.task_type,
            topic_entity=first.topic_entity,
            source_ids=[signal.source_id for signal in cluster],
            deadline_at=min(deadline_at_values) if deadline_at_values else None,
            deadline_hours=min(deadline_values) if deadline_values else None,
            signal_count=len(cluster),
            platforms_seen=sorted(platforms_seen, key=lambda item: item.value),
            sender_roles=sorted(sender_roles, key=lambda item: item.value),
            sender_ids=sender_ids,
            urgency_word_count=max(signal.urgency_word_count for signal in cluster),
            representative_source_id=representative.source_id,
            representative_subject=representative_subject,
            representative_snippet=representative_snippet,
            representative_body_excerpt=representative_body_excerpt,
            representative_sender_display=representative.sender_display,
            representative_timestamp=representative.timestamp,
            manual_tags=dedupe_tags(tag for signal in cluster for tag in signal.manual_tags),
        )

    def _select_representative_signal(self, cluster: list[TaskSignal]) -> TaskSignal:
        def score(signal: TaskSignal) -> tuple[int, int, int, int]:
            subject = (signal.subject or "").strip()
            snippet = (signal.snippet or "").strip()
            body = (signal.body_excerpt or "").strip()
            return (
                1 if subject and subject.lower() != "(no subject)" else 0,
                1 if snippet else 0,
                1 if body else 0,
                signal.urgency_word_count + (1 if signal.deadline_hours is not None else 0),
            )

        return max(cluster, key=score)
