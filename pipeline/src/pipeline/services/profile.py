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
    OnboardingContext,
    SenderWeight,
    TagWeight,
    TaskType,
    TaskTypeWeight,
)
from pipeline.utils.time import utc_now_naive

_PERFORMANCE_TIME_SEEDS = {
    "Morning": {"peak_action_hour": 9, "low_energy_hours": [14, 15, 16, 21, 22]},
    "Afternoon": {"peak_action_hour": 14, "low_energy_hours": [8, 9, 10, 20, 21]},
    "Evening": {"peak_action_hour": 20, "low_energy_hours": [8, 9, 10, 13, 14]},
}


class ProfileService:
    def __init__(self, settings: PipelineSettings) -> None:
        self.settings = settings

    def create_default_profile(
        self,
        user_id: str,
        onboarding_context: OnboardingContext | None = None,
    ) -> BehaviorProfile:
        seed = f"{user_id}:{self.settings.sender_hash_pepper}"
        salt = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        profile = BehaviorProfile(user_id=user_id, user_salt=salt)
        return self._seed_profile_from_onboarding(profile, onboarding_context)

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

        if event.task_type is not None:
            self._update_task_type_weight(updated, event)

        if event.task_type is not None and event.deadline_hours is not None and event.action == FeedbackAction.ACCEPT:
            current = updated.task_type_start_leads.get(event.task_type)
            updated.task_type_start_leads[event.task_type] = self.update_metric_ewma(current, event.deadline_hours)
            updated.action_hours.append(event.occurred_at.hour)
            updated.action_hours = updated.action_hours[-50:]
            self._recompute_action_patterns(updated)

        for tag in event.task_tags:
            self._update_tag_weight(updated, tag, event)

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
        tags: list[str] | None = None,
    ) -> BehaviorProfile:
        updated = profile.model_copy(deep=True)
        updated.profile_version += 1
        occurred = occurred_at or utc_now_naive()

        if deadline_hours is not None:
            current = updated.task_type_start_leads.get(task_type)
            updated.task_type_start_leads[task_type] = self.update_metric_ewma(current, deadline_hours)
            updated.action_hours.append(occurred.hour)
            updated.action_hours = updated.action_hours[-50:]
            self._recompute_action_patterns(updated)

        event = FeedbackEvent(
            user_id=updated.user_id,
            canonical_task_id="manual",
            action=FeedbackAction.ACCEPT,
            occurred_at=occurred,
            task_type=task_type,
            entity_key=entity_key,
            entity_name=entity_name,
            entity_type=entity_type,
            deadline_hours=deadline_hours,
            task_tags=tags or [],
        )
        return self.update_from_feedback(updated.model_copy(update={"profile_version": updated.profile_version - 1}), event)

    def can_personalize(
        self,
        profile: BehaviorProfile,
        *,
        entity_observation_count: int = 0,
        sender_observation_count: int = 0,
        task_type_observation_count: int = 0,
        tag_observation_count: int = 0,
    ) -> bool:
        if profile.confidence < self.settings.profile_confidence_threshold:
            return False
        threshold = self.settings.minimum_personalization_observations
        return any(
            count >= threshold
            for count in (
                entity_observation_count,
                sender_observation_count,
                task_type_observation_count,
                tag_observation_count,
            )
        )

    def _update_confidence(self, profile: BehaviorProfile, action: FeedbackAction) -> None:
        values = deque(profile.decision_window, maxlen=self.settings.decision_window_size)
        values.append(self._decision_window_target(action))
        profile.decision_window = list(values)

    def _decision_window_target(self, action: FeedbackAction) -> float:
        if action == FeedbackAction.ACCEPT:
            return 0.75
        if action == FeedbackAction.COMPLETED:
            return 1.0
        if action in {FeedbackAction.REJECT, FeedbackAction.DELETE}:
            return 0.0
        return 0.5

    def _current_confidence(self, profile: BehaviorProfile) -> float:
        if len(profile.decision_window) < 3:
            return 0.0
        return max(0.15, sum(profile.decision_window) / len(profile.decision_window))

    def _update_task_type_weight(self, profile: BehaviorProfile, event: FeedbackEvent) -> None:
        if event.task_type is None:
            return
        entry = profile.task_type_weights.get(event.task_type)
        if entry is None:
            entry = TaskTypeWeight()

        entry.observation_count += 1
        accept_target = self._accept_target(event.action)
        if accept_target is not None:
            entry.accept_rate = self.update_metric_ewma(entry.accept_rate, accept_target)

        priority_delta = self._priority_delta_from_event(event)
        if event.action == FeedbackAction.WRONG_PRIORITY and priority_delta:
            entry.priority_multiplier = self._apply_priority_delta(entry.priority_multiplier, priority_delta)

        profile.task_type_weights[event.task_type] = entry

    def _update_tag_weight(self, profile: BehaviorProfile, tag: str, event: FeedbackEvent) -> None:
        entry = profile.tag_weights.get(tag)
        if entry is None:
            entry = TagWeight()

        entry.observation_count += 1
        accept_target = self._accept_target(event.action)
        if accept_target is not None:
            entry.accept_rate = self.update_metric_ewma(entry.accept_rate, accept_target)

        priority_delta = self._priority_delta_from_event(event)
        if event.action == FeedbackAction.WRONG_PRIORITY and priority_delta:
            entry.priority_multiplier = self._apply_priority_delta(entry.priority_multiplier, priority_delta)

        profile.tag_weights[tag] = entry

    def _update_entity_weight(self, profile: BehaviorProfile, event: FeedbackEvent) -> None:
        entry = profile.entity_weights.get(event.entity_key)
        if entry is None:
            entry = EntityWeight(
                entity_name=event.entity_name or event.entity_key,
                entity_key=event.entity_key,
                entity_type=event.entity_type or EntityType.TOPIC,
            )

        entry.observation_count += 1
        defer_target = self._defer_target(event.action)
        if defer_target is not None:
            entry.defer_rate = self.update_metric_ewma(entry.defer_rate, defer_target)

        if event.action == FeedbackAction.ACCEPT and event.deadline_hours is not None:
            entry.avg_start_lead_hours = self.update_metric_ewma(entry.avg_start_lead_hours, event.deadline_hours)

        priority_delta = self._priority_delta_from_event(event)
        if event.action == FeedbackAction.WRONG_PRIORITY and priority_delta:
            entry.priority_multiplier = self._apply_priority_delta(entry.priority_multiplier, priority_delta)
        else:
            baseline = 1.5 - (entry.defer_rate if entry.defer_rate is not None else 0.5)
            entry.priority_multiplier = round(min(1.8, max(0.3, baseline)), 2)

        profile.entity_weights[event.entity_key] = entry

    def _update_sender_weight(self, profile: BehaviorProfile, event: FeedbackEvent) -> None:
        sender_hash = event.sender_hash
        if sender_hash is None:
            return

        entry = profile.sender_weights.get(sender_hash)
        if entry is None:
            entry = SenderWeight(sender_hash=sender_hash, label="sender")

        entry.observation_count += 1
        response_target = self._response_target(event.action)
        if response_target is not None:
            entry.response_rate = self.update_metric_ewma(entry.response_rate, response_target)

        if event.action == FeedbackAction.ACCEPT and event.deadline_hours is not None:
            entry.avg_response_lead_hours = self.update_metric_ewma(entry.avg_response_lead_hours, event.deadline_hours)

        priority_delta = self._priority_delta_from_event(event)
        if event.action == FeedbackAction.WRONG_PRIORITY and priority_delta:
            entry.weight = self._apply_priority_delta(entry.weight, priority_delta)
        else:
            baseline = 0.6 + ((entry.response_rate if entry.response_rate is not None else 0.5) * 0.9)
            entry.weight = round(min(1.8, max(0.3, baseline)), 2)

        profile.sender_weights[sender_hash] = entry

    def _accept_target(self, action: FeedbackAction) -> float | None:
        if action == FeedbackAction.ACCEPT:
            return 0.75
        if action == FeedbackAction.COMPLETED:
            return 1.0
        if action in {FeedbackAction.REJECT, FeedbackAction.DELETE}:
            return 0.0
        return None

    def _defer_target(self, action: FeedbackAction) -> float | None:
        if action == FeedbackAction.ACCEPT:
            return 0.25
        if action == FeedbackAction.COMPLETED:
            return 0.0
        if action in {FeedbackAction.REJECT, FeedbackAction.DELETE}:
            return 1.0
        return None

    def _response_target(self, action: FeedbackAction) -> float | None:
        if action == FeedbackAction.ACCEPT:
            return 0.75
        if action == FeedbackAction.COMPLETED:
            return 1.0
        if action in {FeedbackAction.REJECT, FeedbackAction.DELETE}:
            return 0.0
        return None

    def _apply_priority_delta(self, current_value: float, incremental_delta: int) -> float:
        adjusted = current_value + (0.1 * incremental_delta)
        return round(min(1.8, max(0.3, adjusted)), 2)

    def _priority_delta_from_event(self, event: FeedbackEvent) -> int:
        if event.action != FeedbackAction.WRONG_PRIORITY:
            return 0
        if event.incremental_priority_delta:
            return event.incremental_priority_delta
        if event.direction == FeedbackDirection.TOO_LOW:
            return 1
        if event.direction == FeedbackDirection.TOO_HIGH:
            return -1
        return 0

    def _recompute_action_patterns(self, profile: BehaviorProfile) -> None:
        if len(profile.action_hours) >= 5:
            counter = Counter(profile.action_hours)
            profile.peak_action_hour = counter.most_common(1)[0][0]
            low_frequency_hours = [hour for hour, count in counter.items() if count <= 1]
            profile.low_energy_hours = sorted(low_frequency_hours)[:5]

    def _seed_profile_from_onboarding(
        self,
        profile: BehaviorProfile,
        onboarding_context: OnboardingContext | None,
    ) -> BehaviorProfile:
        if onboarding_context is None:
            return profile

        performance_time = dict(onboarding_context.static_preferences).get("performance_time")
        if performance_time not in _PERFORMANCE_TIME_SEEDS:
            return profile

        seeded_pattern = _PERFORMANCE_TIME_SEEDS[performance_time]
        return profile.model_copy(
            update={
                "peak_action_hour": seeded_pattern["peak_action_hour"],
                "low_energy_hours": list(seeded_pattern["low_energy_hours"]),
            }
        )
