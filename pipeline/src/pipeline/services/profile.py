from __future__ import annotations

import hashlib
from collections import Counter, deque
from datetime import datetime

from pipeline.config import PipelineSettings
from pipeline.models import (
    BehaviorProfile,
    EntityType,
    EntityWeight,
    FeedbackAction,
    FeedbackDirection,
    FeedbackEvent,
    SenderWeight,
    TaskType,
)


class ProfileService:
    def __init__(self, settings: PipelineSettings) -> None:
        self.settings = settings

    def create_default_profile(self, user_id: str) -> BehaviorProfile:
        seed = f"{user_id}:{self.settings.sender_hash_pepper}"
        salt = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        return BehaviorProfile(user_id=user_id, user_salt=salt)

    def hash_identity(self, *, user_salt: str, identifier: str) -> str:
        material = f"{user_salt}:{self.settings.sender_hash_pepper}:{identifier.strip().lower()}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    def update_metric_ewma(self, current_value: float | None, new_observation: float) -> float:
        if current_value is None:
            return new_observation
        decay = self.settings.ewma_decay
        return decay * current_value + (1 - decay) * new_observation

    def update_from_feedback(self, profile: BehaviorProfile, event: FeedbackEvent) -> BehaviorProfile:
        updated = profile.model_copy(deep=True)
        updated.profile_version += 1

        self._update_confidence(updated, event.action)

        if event.task_type is not None and event.deadline_hours is not None and event.action == FeedbackAction.GOT_IT:
            current = updated.task_type_start_leads.get(event.task_type)
            updated.task_type_start_leads[event.task_type] = self.update_metric_ewma(current, event.deadline_hours)
            updated.action_hours.append(event.occurred_at.hour)
            updated.action_hours = updated.action_hours[-50:]
            self._recompute_action_patterns(updated)

        if event.entity_key and event.entity_name and event.entity_type:
            self._update_entity_weight(updated, event)

        if event.sender_hash:
            self._update_sender_weight(updated, event)

        updated.confidence = self._current_confidence(updated)
        return updated

    def update_from_manual_task(
        self,
        profile: BehaviorProfile,
        *,
        task_type: TaskType,
        entity_key: str,
        entity_name: str,
        entity_type: EntityType,
        deadline_hours: float | None,
        occurred_at: datetime | None = None,
    ) -> BehaviorProfile:
        updated = profile.model_copy(deep=True)
        updated.profile_version += 1
        occurred = occurred_at or datetime.now()

        if deadline_hours is not None:
            current = updated.task_type_start_leads.get(task_type)
            updated.task_type_start_leads[task_type] = self.update_metric_ewma(current, deadline_hours)
            updated.action_hours.append(occurred.hour)
            updated.action_hours = updated.action_hours[-50:]
            self._recompute_action_patterns(updated)

        entry = updated.entity_weights.get(entity_key)
        if entry is None:
            entry = EntityWeight(
                entity_name=entity_name,
                entity_key=entity_key,
                entity_type=entity_type,
                defer_rate=0.2,
                priority_multiplier=1.3,
            )

        entry.observation_count += 1
        entry.defer_rate = self.update_metric_ewma(entry.defer_rate, 0.0)

        if deadline_hours is not None:
            entry.avg_start_lead_hours = self.update_metric_ewma(entry.avg_start_lead_hours, deadline_hours)

        multiplier = 1.5 - (entry.defer_rate if entry.defer_rate is not None else 0.2)
        entry.priority_multiplier = round(min(1.8, max(0.4, multiplier)), 2)
        updated.entity_weights[entity_key] = entry
        return updated

    def can_personalize(
        self,
        profile: BehaviorProfile,
        *,
        entity_observation_count: int = 0,
        sender_observation_count: int = 0,
    ) -> bool:
        if profile.confidence < self.settings.profile_confidence_threshold:
            return False
        return (
            entity_observation_count >= self.settings.minimum_personalization_observations
            or sender_observation_count >= self.settings.minimum_personalization_observations
        )

    def _update_confidence(self, profile: BehaviorProfile, action: FeedbackAction) -> None:
        values = deque(profile.decision_window, maxlen=self.settings.decision_window_size)
        if action == FeedbackAction.GOT_IT:
            values.append(1.0)
        elif action == FeedbackAction.ALREADY_DONE:
            values.append(0.5)
        else:
            values.append(0.0)
        profile.decision_window = list(values)

    def _current_confidence(self, profile: BehaviorProfile) -> float:
        if len(profile.decision_window) < 3:
            return 0.0
        return max(0.15, sum(profile.decision_window) / len(profile.decision_window))

    def _update_entity_weight(self, profile: BehaviorProfile, event: FeedbackEvent) -> None:
        entry = profile.entity_weights.get(event.entity_key)
        if entry is None:
            entry = EntityWeight(
                entity_name=event.entity_name or event.entity_key,
                entity_key=event.entity_key,
                entity_type=event.entity_type or EntityType.TOPIC,
            )

        entry.observation_count += 1

        defer_signal = self._feedback_to_defer_signal(event)
        entry.defer_rate = self.update_metric_ewma(entry.defer_rate, defer_signal)

        if event.action == FeedbackAction.GOT_IT and event.deadline_hours is not None:
            entry.avg_start_lead_hours = self.update_metric_ewma(entry.avg_start_lead_hours, event.deadline_hours)

        multiplier = 1.5 - (entry.defer_rate if entry.defer_rate is not None else 0.5)
        if event.action == FeedbackAction.WRONG_PRIORITY and event.direction == FeedbackDirection.TOO_LOW:
            multiplier += 0.1
        if event.action == FeedbackAction.WRONG_PRIORITY and event.direction == FeedbackDirection.TOO_HIGH:
            multiplier -= 0.1
        entry.priority_multiplier = round(min(1.8, max(0.3, multiplier)), 2)
        profile.entity_weights[event.entity_key] = entry

    def _update_sender_weight(self, profile: BehaviorProfile, event: FeedbackEvent) -> None:
        sender_hash = event.sender_hash
        if sender_hash is None:
            return

        entry = profile.sender_weights.get(sender_hash)
        if entry is None:
            entry = SenderWeight(sender_hash=sender_hash, label="sender")

        entry.observation_count += 1
        response_signal = self._feedback_to_response_signal(event)
        entry.response_rate = self.update_metric_ewma(entry.response_rate, response_signal)

        if event.action == FeedbackAction.GOT_IT and event.deadline_hours is not None:
            entry.avg_response_lead_hours = self.update_metric_ewma(entry.avg_response_lead_hours, event.deadline_hours)

        weight = 0.6 + ((entry.response_rate if entry.response_rate is not None else 0.5) * 0.9)
        if event.action == FeedbackAction.WRONG_PRIORITY and event.direction == FeedbackDirection.TOO_LOW:
            weight += 0.1
        if event.action == FeedbackAction.WRONG_PRIORITY and event.direction == FeedbackDirection.TOO_HIGH:
            weight -= 0.1
        entry.weight = round(min(1.8, max(0.3, weight)), 2)
        profile.sender_weights[sender_hash] = entry

    def _recompute_action_patterns(self, profile: BehaviorProfile) -> None:
        if len(profile.action_hours) >= 5:
            counter = Counter(profile.action_hours)
            profile.peak_action_hour = counter.most_common(1)[0][0]

            low_frequency_hours = [hour for hour, count in counter.items() if count <= 1]
            profile.low_energy_hours = sorted(low_frequency_hours)[:5]

    def _feedback_to_defer_signal(self, event: FeedbackEvent) -> float:
        if event.action == FeedbackAction.RESCHEDULE:
            return 1.0
        if event.action == FeedbackAction.WRONG_PRIORITY and event.direction == FeedbackDirection.TOO_HIGH:
            return 1.0
        if event.action == FeedbackAction.WRONG_PRIORITY and event.direction == FeedbackDirection.TOO_LOW:
            return 0.0
        if event.action == FeedbackAction.ALREADY_DONE:
            return 0.4
        return 0.0

    def _feedback_to_response_signal(self, event: FeedbackEvent) -> float:
        if event.action == FeedbackAction.GOT_IT:
            return 1.0
        if event.action == FeedbackAction.ALREADY_DONE:
            return 0.5
        if event.action == FeedbackAction.WRONG_PRIORITY and event.direction == FeedbackDirection.TOO_LOW:
            return 1.0
        return 0.0
