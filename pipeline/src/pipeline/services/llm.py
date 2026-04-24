from __future__ import annotations

import json
import logging
import os
from typing import Any

from pipeline.config import PipelineSettings
from pipeline.models import (
    ActionWindow,
    BehaviorProfile,
    CanonicalTask,
    EntityWeight,
    LlmDecision,
    OnboardingContext,
    PriorityTier,
    SenderWeight,
    StructuredLlmOutput,
)
from pipeline.models.enums import TaskType
from pipeline.utils.env import load_dotenv_value
from pipeline.utils.tags import filter_allowed_tags, merge_tag_catalog, synthesize_task_tags
from pipeline.utils.time import current_hour_for_timezone

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None


logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
You are a student priority reasoning engine.
You receive a structured task object, a generic pre-scored priority tier, user profile context, and calendar context.

Rules:
- Start from the pre-scored tier.
- If can_personalize is true, use learned profile weights as the strongest personalization signals.
- If can_personalize is false, you may use onboarding preferences as a lightweight starter signal, but any onboarding-only priority change must be at most one tier.
- Use task_type_priority_multiplier, entity_priority_multiplier, sender_weight, tag preferences, and start-lead signals only when they are present.
- Treat onboarding preferences as initial setup only. Behavioral history should outweigh onboarding once available.
- Timetable context can affect action timing and rationale, but must not directly change the priority tier.
- Return up to 3 tags.
- Tags must come only from available_tags.
- Keep the rationale compact and specific.
- Return only valid JSON matching the provided schema.
"""

FEW_SHOT_EXAMPLES = [
    {
        "input": {
            "task": {
                "type": "submission",
                "deadline_hours": 8.0,
                "entity_name": "CS2103T",
                "entity_type": "module",
                "platforms_seen": ["gmail", "teams"],
                "signal_count": 4,
                "pre_scored_tier": "HIGH",
                "score_reasons": ["deadline under 24 hours", "mentioned 4 times across platforms", "graded submission"],
                "manual_tags": [],
            },
            "user_context": {
                "task_type_start_lead_hours": 10.0,
                "task_type_priority_multiplier": 1.3,
                "entity_priority_multiplier": 1.45,
                "entity_defer_rate": 0.05,
                "entity_avg_start_lead_hours": 9.2,
                "entity_observation_count": 12,
                "sender_response_rate": 0.92,
                "sender_weight": 1.55,
                "sender_observation_count": 10,
                "tag_preferences": [{"tag": "assignment", "accept_rate": 0.9, "priority_multiplier": 1.4}],
                "peak_action_hour": 21,
                "low_energy_hours": [13, 14, 15],
                "current_hour": 20,
                "profile_confidence": 0.81,
                "can_personalize": True,
            },
            "calendar_context": {
                "timezone": "Asia/Singapore",
                "timetable_summary": "Evening work session available",
                "busy_windows": [],
                "recurring_task_notes": [],
                "available_tags": ["assignment", "deadline", "urgent", "project"],
            },
        },
        "output": {
            "priority_tier": "CRITICAL",
            "action_window": "NOW",
            "rationale": "Due in 8 hours and already inside the user's normal start buffer for this kind of work.",
            "confidence": 0.93,
            "profile_adjustment_made": True,
            "adjustment_reason": "Escalated from HIGH because the remaining time is below the user's typical start lead.",
            "tags": ["assignment", "deadline", "urgent"],
        },
    },
    {
        "input": {
            "task": {
                "type": "admin",
                "deadline_hours": 48.0,
                "entity_name": "Registrar",
                "entity_type": "topic",
                "platforms_seen": ["gmail"],
                "signal_count": 1,
                "pre_scored_tier": "MEDIUM",
                "score_reasons": ["deadline within 3 days", "from institution"],
                "manual_tags": [],
            },
            "user_context": {
                "task_type_start_lead_hours": None,
                "task_type_priority_multiplier": 1.0,
                "entity_priority_multiplier": 0.9,
                "entity_defer_rate": 0.78,
                "entity_avg_start_lead_hours": None,
                "entity_observation_count": 9,
                "sender_response_rate": 0.66,
                "sender_weight": 1.02,
                "sender_observation_count": 7,
                "tag_preferences": [{"tag": "admin", "accept_rate": 0.8, "priority_multiplier": 1.1}],
                "peak_action_hour": 21,
                "low_energy_hours": [13, 14, 15],
                "current_hour": 10,
                "profile_confidence": 0.74,
                "can_personalize": True,
            },
            "calendar_context": {
                "timezone": "Asia/Singapore",
                "timetable_summary": "Afternoon classes, evening free",
                "busy_windows": [],
                "recurring_task_notes": [],
                "available_tags": ["admin", "deadline", "optional"],
            },
        },
        "output": {
            "priority_tier": "MEDIUM",
            "action_window": "TODAY",
            "rationale": "Keep this at MEDIUM because the deadline is still about 48 hours away, but it is worth handling today.",
            "confidence": 0.82,
            "profile_adjustment_made": False,
            "adjustment_reason": "The evidence did not justify a tier change.",
            "tags": ["admin", "deadline"],
        },
    },
    {
        "input": {
            "task": {
                "type": "meeting",
                "deadline_hours": 18.0,
                "entity_name": "CCA welfare pack collection",
                "entity_type": "cca",
                "platforms_seen": ["gmail"],
                "signal_count": 1,
                "pre_scored_tier": "MEDIUM",
                "score_reasons": ["deadline under 24 hours", "scheduled meeting"],
                "manual_tags": [],
            },
            "user_context": {
                "task_type_start_lead_hours": None,
                "task_type_priority_multiplier": None,
                "entity_priority_multiplier": None,
                "entity_defer_rate": None,
                "entity_avg_start_lead_hours": None,
                "entity_observation_count": 0,
                "sender_response_rate": None,
                "sender_weight": None,
                "sender_observation_count": 0,
                "tag_preferences": [],
                "peak_action_hour": 21,
                "low_energy_hours": [13, 14, 15],
                "current_hour": 14,
                "profile_confidence": 0.12,
                "can_personalize": False,
            },
            "calendar_context": {
                "timezone": "Asia/Singapore",
                "timetable_summary": "Busy this afternoon, free after 6pm",
                "busy_windows": [
                    {
                        "start_iso": "2026-04-22T13:00:00+08:00",
                        "end_iso": "2026-04-22T17:00:00+08:00",
                        "label": "Classes",
                    }
                ],
                "recurring_task_notes": [],
                "available_tags": ["group_work", "announcement", "optional"],
            },
        },
        "output": {
            "priority_tier": "MEDIUM",
            "action_window": "TODAY",
            "rationale": "Keep the pre-scored MEDIUM tier because there is not enough reliable history to personalize yet.",
            "confidence": 0.78,
            "profile_adjustment_made": False,
            "adjustment_reason": "No profile-based adjustment was made because profile confidence and observation counts are too low.",
            "tags": ["group_work", "announcement"],
        },
    },
]


class PriorityReasoner:
    def __init__(self, settings: PipelineSettings, client: Any | None = None) -> None:
        self.settings = settings
        self.client = client
        self._provider_status_logged = False

    def build_llm_input(
        self,
        *,
        task: CanonicalTask,
        profile: BehaviorProfile,
        onboarding: OnboardingContext,
        entity_context: EntityWeight | None,
        sender_context: SenderWeight | None,
        can_personalize: bool,
        available_tags: list[str] | None = None,
        current_hour: int | None = None,
    ) -> dict[str, Any]:
        timezone_name = onboarding.timezone or self.settings.provider_timezone_fallback
        now_hour = (
            current_hour
            if current_hour is not None
            else current_hour_for_timezone(timezone_name, fallback=self.settings.provider_timezone_fallback)
        )
        task_type_context = profile.task_type_weights.get(task.task_type)
        tag_preferences = [
            {
                "tag": tag,
                "accept_rate": profile.tag_weights[tag].accept_rate,
                "priority_multiplier": profile.tag_weights[tag].priority_multiplier,
                "observation_count": profile.tag_weights[tag].observation_count,
            }
            for tag in task.manual_tags
            if tag in profile.tag_weights
        ]
        if not tag_preferences:
            top_tags = sorted(
                profile.tag_weights.items(),
                key=lambda item: (
                    item[1].priority_multiplier,
                    item[1].accept_rate or 0.0,
                    item[1].observation_count,
                ),
                reverse=True,
            )[:5]
            tag_preferences = [
                {
                    "tag": tag,
                    "accept_rate": weight.accept_rate,
                    "priority_multiplier": weight.priority_multiplier,
                    "observation_count": weight.observation_count,
                }
                for tag, weight in top_tags
            ]

        return {
            "task": {
                "type": task.task_type.value,
                "deadline_hours": task.deadline_hours,
                "entity_name": task.topic_entity.entity_name,
                "entity_type": task.topic_entity.entity_type.value,
                "subject": task.representative_subject,
                "preview": task.representative_body_excerpt or task.representative_snippet,
                "sender_display": task.representative_sender_display,
                "platforms_seen": [platform.value for platform in task.platforms_seen],
                "signal_count": task.signal_count,
                "pre_scored_tier": task.priority_tier.value if task.priority_tier else PriorityTier.LOW.value,
                "score_reasons": task.score_reasons,
                "manual_tags": task.manual_tags,
                "origin": task.origin.value,
                "sender_roles": [role.value for role in task.sender_roles],
            },
            "user_context": {
                "task_type_start_lead_hours": profile.task_type_start_leads.get(task.task_type),
                "task_type_accept_rate": task_type_context.accept_rate if task_type_context else None,
                "task_type_priority_multiplier": task_type_context.priority_multiplier if task_type_context else None,
                "task_type_observation_count": task_type_context.observation_count if task_type_context else 0,
                "entity_priority_multiplier": entity_context.priority_multiplier if entity_context else None,
                "entity_defer_rate": entity_context.defer_rate if entity_context else None,
                "entity_avg_start_lead_hours": entity_context.avg_start_lead_hours if entity_context else None,
                "entity_observation_count": entity_context.observation_count if entity_context else 0,
                "sender_response_rate": sender_context.response_rate if sender_context else None,
                "sender_weight": sender_context.weight if sender_context else None,
                "sender_observation_count": sender_context.observation_count if sender_context else 0,
                "tag_preferences": tag_preferences,
                "peak_action_hour": profile.peak_action_hour,
                "low_energy_hours": profile.low_energy_hours,
                "current_hour": now_hour,
                "profile_confidence": profile.confidence,
                "can_personalize": can_personalize,
                "initial_performance_time": onboarding.static_preferences.get("performance_time"),
                "initial_focus_area": onboarding.static_preferences.get("important_topic"),
                "initial_priority_lens": onboarding.static_preferences.get("prioritise_by"),
            },
            "calendar_context": {
                "timezone": onboarding.timezone,
                "timetable_summary": onboarding.timetable_summary,
                "busy_windows": [window.model_dump(mode="json") for window in onboarding.busy_windows],
                "recurring_task_notes": onboarding.recurring_task_notes,
                "available_tags": merge_tag_catalog(available_tags),
            },
        }

    def reason_task(
        self,
        *,
        run_id: str,
        task: CanonicalTask,
        llm_input: dict[str, Any],
    ) -> tuple[StructuredLlmOutput, LlmDecision]:
        request_payload = {
            "system_prompt": SYSTEM_PROMPT.strip(),
            "input": llm_input,
            "schema": self._response_schema(),
        }

        output = self._sanitize_output(self._call_openai(request_payload), llm_input)
        decision = LlmDecision(
            run_id=run_id,
            canonical_task_id=task.canonical_task_id,
            prompt_version=self.settings.llm_prompt_version,
            schema_version_ref=self.settings.llm_schema_version,
            model=self.settings.llm_model,
            request_payload=request_payload,
            response_payload=output.model_dump(mode="json"),
        )
        return output, decision

    def _sanitize_output(self, output: StructuredLlmOutput, llm_input: dict[str, Any]) -> StructuredLlmOutput:
        available_tags = llm_input.get("calendar_context", {}).get("available_tags", [])
        tags = filter_allowed_tags(output.tags, available_tags, max_count=3)
        return output.model_copy(update={"tags": tags})

    def _call_openai(self, request_payload: dict[str, Any]) -> StructuredLlmOutput:
        api_key = os.environ.get("OPENAI_API_KEY") or load_dotenv_value("OPENAI_API_KEY")
        self._log_provider_status_once(api_key=api_key)
        if self.client is None and OpenAI is not None and api_key:  # pragma: no cover - networkless by default
            self.client = OpenAI(api_key=api_key)

        if self.client is None:
            return self._fallback_reasoning(request_payload["input"])

        try:  # pragma: no cover - external API
            response = self.client.responses.create(
                model=self.settings.llm_model,
                input=self._request_messages(request_payload["input"]),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "priority_task_card",
                        "schema": self._response_schema(),
                        "strict": True,
                    }
                },
            )
            return StructuredLlmOutput.model_validate_json(response.output_text)
        except Exception:
            return self._fallback_reasoning(request_payload["input"])

    def _log_provider_status_once(self, *, api_key: str | None) -> None:
        if self._provider_status_logged:
            return

        self._provider_status_logged = True
        has_api_key = bool(api_key)
        has_openai_sdk = OpenAI is not None

        if has_api_key and has_openai_sdk:
            logger.info(
                "Priority reasoner provider status: OPENAI_API_KEY detected; OpenAI reasoning is enabled."
            )
            return

        if has_api_key and not has_openai_sdk:
            logger.warning(
                "Priority reasoner provider status: OPENAI_API_KEY detected but the openai package is unavailable; using fallback reasoning."
            )
            return

        logger.info(
            "Priority reasoner provider status: OPENAI_API_KEY not detected; using fallback reasoning."
        )

    def _request_messages(self, llm_input: dict[str, Any]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT.strip()}]}
        ]
        for example in FEW_SHOT_EXAMPLES:
            messages.append(
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(example["input"])}],
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(example["output"])}],
                }
            )
        messages.append(
            {
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(llm_input)}],
            }
        )
        return messages

    def _response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "priority_tier": {
                    "type": "string",
                    "enum": [tier.value for tier in PriorityTier],
                },
                "action_window": {
                    "type": "string",
                    "enum": [window.value for window in ActionWindow],
                },
                "rationale": {"type": "string"},
                "confidence": {"type": "number"},
                "profile_adjustment_made": {"type": "boolean"},
                "adjustment_reason": {
                    "anyOf": [{"type": "string"}, {"type": "null"}]
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "priority_tier",
                "action_window",
                "rationale",
                "confidence",
                "profile_adjustment_made",
                "adjustment_reason",
                "tags",
            ],
        }

    def _fallback_reasoning(self, llm_input: dict[str, Any]) -> StructuredLlmOutput:
        task = llm_input["task"]
        user = llm_input["user_context"]
        calendar = llm_input["calendar_context"]
        tier = PriorityTier(task["pre_scored_tier"])
        adjustment_reason = None
        adjusted = False

        if user["can_personalize"]:
            entity_multiplier = user.get("entity_priority_multiplier")
            sender_weight = user.get("sender_weight")
            task_type_lead = user.get("task_type_start_lead_hours")
            task_type_priority_multiplier = user.get("task_type_priority_multiplier")
            deadline_hours = task.get("deadline_hours")

            if (
                deadline_hours is not None
                and task_type_lead is not None
                and deadline_hours < task_type_lead
                and tier != PriorityTier.CRITICAL
            ):
                tier = self._raise_tier(tier)
                adjusted = True
                adjustment_reason = (
                    "Escalated because personal start-lead behavior shows the task is already inside the user's normal buffer."
                )
            elif entity_multiplier is not None and entity_multiplier <= 0.75 and tier in {PriorityTier.HIGH, PriorityTier.MEDIUM}:
                tier = self._lower_tier(tier)
                adjusted = True
                adjustment_reason = "Lowered because recent entity-level behavior shows the user consistently defers this topic."
            elif sender_weight is not None and sender_weight >= 1.4 and tier != PriorityTier.CRITICAL:
                tier = self._raise_tier(tier)
                adjusted = True
                adjustment_reason = "Escalated because the user responds quickly to this sender."
            elif task_type_priority_multiplier is not None and task_type_priority_multiplier >= 1.4 and tier != PriorityTier.CRITICAL:
                tier = self._raise_tier(tier)
                adjusted = True
                adjustment_reason = "Escalated because this task type usually matters more for this user."
        else:
            tier, adjustment_reason = self._apply_onboarding_preference_nudge(task=task, user=user, tier=tier)
            adjusted = adjustment_reason is not None

        action_window = self._choose_action_window(task=task, user=user, calendar_context=calendar)
        rationale = self._build_rationale(task=task, user=user, action_window=action_window)
        confidence = self._estimate_fallback_confidence(
            task=task,
            user=user,
            action_window=action_window,
            adjusted=adjusted,
        )

        tags = synthesize_task_tags(
            task_type=TaskType(task["type"]) if task.get("type") else None,
            text_parts=[
                task.get("subject"),
                task.get("preview"),
                task.get("sender_display"),
                task.get("entity_name"),
                task.get("type"),
            ],
            score_reasons=task.get("score_reasons") or [],
            manual_tags=task.get("manual_tags", []),
            llm_tags=[],
            available_tags=calendar.get("available_tags", []),
            max_count=3,
        )

        return StructuredLlmOutput(
            priority_tier=tier,
            action_window=action_window,
            rationale=rationale,
            confidence=confidence,
            profile_adjustment_made=adjusted,
            adjustment_reason=adjustment_reason,
            tags=tags,
        )

    def _estimate_fallback_confidence(
        self,
        *,
        task: dict[str, Any],
        user: dict[str, Any],
        action_window: ActionWindow,
        adjusted: bool,
    ) -> float:
        confidence = 0.22
        deadline_hours = task.get("deadline_hours")
        signal_count = int(task.get("signal_count") or 0)
        score_reasons = task.get("score_reasons") or []
        profile_confidence = float(user.get("profile_confidence") or 0.0)
        pre_scored_tier = str(task.get("pre_scored_tier") or PriorityTier.LOW.value)

        if deadline_hours is not None:
            if deadline_hours <= 6:
                confidence += 0.18
            elif deadline_hours <= 24:
                confidence += 0.15
            elif deadline_hours <= 72:
                confidence += 0.1
            else:
                confidence += 0.05

        confidence += min(signal_count, 4) * 0.07
        confidence += min(len(score_reasons), 3) * 0.05

        if task.get("subject"):
            confidence += 0.03
        if task.get("preview"):
            confidence += 0.04

        if pre_scored_tier == PriorityTier.CRITICAL.value:
            confidence += 0.12
        elif pre_scored_tier == PriorityTier.HIGH.value:
            confidence += 0.08
        elif pre_scored_tier == PriorityTier.MEDIUM.value:
            confidence += 0.04

        if action_window == ActionWindow.NOW:
            confidence += 0.05
        elif action_window == ActionWindow.TODAY:
            confidence += 0.03

        if user.get("can_personalize"):
            confidence += min(profile_confidence, 1.0) * 0.12
            if (user.get("entity_observation_count") or 0) >= 3:
                confidence += 0.03
            if (user.get("sender_observation_count") or 0) >= 3:
                confidence += 0.03
            if (user.get("task_type_observation_count") or 0) >= 3:
                confidence += 0.03
            if adjusted:
                confidence += 0.04
        else:
            confidence += min(profile_confidence, 0.4) * 0.08
            if deadline_hours is None and signal_count <= 1 and len(score_reasons) <= 1:
                confidence -= 0.06

        return round(max(0.3, min(0.95, confidence)), 2)

    def _choose_action_window(self, *, task: dict[str, Any], user: dict[str, Any], calendar_context: dict[str, Any]) -> ActionWindow:
        deadline_hours = task.get("deadline_hours")
        low_energy_hours = set(user.get("low_energy_hours") or [])
        current_hour = user.get("current_hour")

        if deadline_hours is not None and deadline_hours <= 6:
            return ActionWindow.NOW
        if deadline_hours is not None and deadline_hours <= 24:
            return ActionWindow.TODAY if current_hour not in low_energy_hours else ActionWindow.NOW
        if calendar_context.get("busy_windows"):
            return ActionWindow.TODAY
        if deadline_hours is not None and deadline_hours <= 72:
            return ActionWindow.TODAY
        return ActionWindow.THIS_WEEK

    def _build_rationale(self, *, task: dict[str, Any], user: dict[str, Any], action_window: ActionWindow) -> str:
        deadline_hours = task.get("deadline_hours")
        reasons = task.get("score_reasons") or []
        fragments: list[str] = []

        if deadline_hours is not None:
            fragments.append(f"Due in {round(deadline_hours)} hours.")
        else:
            fragments.append(f"Kept at {task['pre_scored_tier']}.")

        if reasons:
            fragments.append(f"Signals: {', '.join(reasons[:2])}.")

        if user.get("can_personalize") and user.get("task_type_start_lead_hours") is not None:
            fragments.append(
                f"This is close to the user's usual start buffer of {round(user['task_type_start_lead_hours'], 1)} hours."
            )
        elif user.get("initial_performance_time"):
            fragments.append(
                f"The current timing still leans on the user's onboarding preference for {str(user['initial_performance_time']).lower()} work."
            )
        elif not user.get("can_personalize"):
            fragments.append("The base tier was kept because there is not enough reliable profile history yet.")

        if action_window == ActionWindow.NOW:
            fragments.append("Best handled now.")
        elif action_window == ActionWindow.TODAY:
            fragments.append("Best handled later today.")
        elif action_window == ActionWindow.THIS_WEEK:
            fragments.append("Best scheduled this week.")
        else:
            fragments.append("Can be deferred for now.")

        return " ".join(fragments[:4])

    def _raise_tier(self, tier: PriorityTier) -> PriorityTier:
        if tier == PriorityTier.LOW:
            return PriorityTier.MEDIUM
        if tier == PriorityTier.MEDIUM:
            return PriorityTier.HIGH
        return PriorityTier.CRITICAL

    def _lower_tier(self, tier: PriorityTier) -> PriorityTier:
        if tier == PriorityTier.CRITICAL:
            return PriorityTier.HIGH
        if tier == PriorityTier.HIGH:
            return PriorityTier.MEDIUM
        return PriorityTier.LOW

    def _apply_onboarding_preference_nudge(
        self,
        *,
        task: dict[str, Any],
        user: dict[str, Any],
        tier: PriorityTier,
    ) -> tuple[PriorityTier, str | None]:
        priority_lens = user.get("initial_priority_lens")
        focus_area = user.get("initial_focus_area")
        deadline_hours = task.get("deadline_hours")
        sender_roles = set(task.get("sender_roles") or [])
        task_type = task.get("type")

        if priority_lens == "Urgency" and deadline_hours is not None and deadline_hours <= 24 and tier != PriorityTier.CRITICAL:
            return (
                self._raise_tier(tier),
                "Escalated one tier because the user's onboarding preference leans toward urgency-first triage.",
            )
        if (
            priority_lens == "Who it's from"
            and sender_roles.intersection({"lecturer", "institution"})
            and tier != PriorityTier.CRITICAL
        ):
            return (
                self._raise_tier(tier),
                "Escalated one tier because the user's onboarding preference gives more weight to sender importance.",
            )
        if (
            priority_lens == "Overall importance"
            and task_type in {TaskType.SUBMISSION.value, TaskType.MEETING.value}
            and tier != PriorityTier.CRITICAL
        ):
            return (
                self._raise_tier(tier),
                "Escalated one tier because the user's onboarding preference leans toward overall importance.",
            )
        if (
            focus_area == "Classes and assignments"
            and task_type in {TaskType.SUBMISSION.value, TaskType.READING.value}
            and tier != PriorityTier.CRITICAL
        ):
            return (
                self._raise_tier(tier),
                "Escalated one tier because the user's onboarding context emphasizes classes and assignments.",
            )
        if (
            focus_area == "External meetings and events"
            and task_type == TaskType.MEETING.value
            and tier != PriorityTier.CRITICAL
        ):
            return (
                self._raise_tier(tier),
                "Escalated one tier because the user's onboarding context emphasizes meetings and events.",
            )
        if (
            focus_area == "Personal goals"
            and task_type == TaskType.SOCIAL.value
            and tier != PriorityTier.CRITICAL
        ):
            return (
                self._raise_tier(tier),
                "Escalated one tier because the user's onboarding context emphasizes personal goals.",
            )
        return tier, None
