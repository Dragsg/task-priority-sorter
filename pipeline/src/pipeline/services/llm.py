from __future__ import annotations

import json
import os
from datetime import datetime
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
from pipeline.models.enums import FeedbackDirection
from pipeline.utils.env import load_dotenv_value
from pipeline.utils.time import current_hour_for_timezone

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None


SYSTEM_PROMPT = """
You are a student priority reasoning engine.
You receive a structured task object, a generic pre-scored priority tier, user profile context, and calendar context.

Rules:
- Start from the pre-scored tier and only adjust it when can_personalize is true.
- If can_personalize is false, preserve the pre-scored tier and explain why personalization was not applied.
- Use entity_priority_multiplier, sender_weight, entity_avg_start_lead_hours, task_type_start_lead_hours, and observation counts only when they are present.
- If the user appears to be inside their usual start buffer, escalating one tier is reasonable.
- If an entity is often deferred, mention the risk in the rationale, but do not lower the tier unless the structured context clearly supports it.
- Timetable context can affect action timing and rationale, but must not directly change the priority tier.
- Keep the rationale compact and specific. Prefer 1 short sentence, use 2 only when needed.
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
            },
            "user_context": {
                "task_type_start_lead_hours": 10.0,
                "entity_priority_multiplier": 1.45,
                "entity_defer_rate": 0.05,
                "entity_avg_start_lead_hours": 9.2,
                "entity_observation_count": 12,
                "sender_response_rate": 0.92,
                "sender_weight": 1.55,
                "sender_observation_count": 10,
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
            },
        },
        "output": {
            "priority_tier": "CRITICAL",
            "action_window": "NOW",
            "rationale": "Due in 8 hours and repeated across Gmail and Teams; the user usually starts this kind of work about 10 hours ahead, so this is already inside their normal buffer.",
            "confidence": 0.93,
            "profile_adjustment_made": True,
            "adjustment_reason": "Escalated from HIGH because can_personalize is true and the remaining time is below the user's typical start lead for this task.",
        },
    },
    {
        "input": {
            "task": {
                "type": "reading",
                "deadline_hours": 48.0,
                "entity_name": "History reading",
                "entity_type": "topic",
                "platforms_seen": ["gmail"],
                "signal_count": 1,
                "pre_scored_tier": "MEDIUM",
                "score_reasons": ["deadline within 3 days", "from lecturer", "reading task"],
            },
            "user_context": {
                "task_type_start_lead_hours": None,
                "entity_priority_multiplier": 0.85,
                "entity_defer_rate": 0.78,
                "entity_avg_start_lead_hours": None,
                "entity_observation_count": 9,
                "sender_response_rate": 0.66,
                "sender_weight": 1.02,
                "sender_observation_count": 7,
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
            },
        },
        "output": {
            "priority_tier": "MEDIUM",
            "action_window": "TODAY",
            "rationale": "Keep this at MEDIUM: the deadline is still about 48 hours away, but the high defer rate makes it worth surfacing today.",
            "confidence": 0.82,
            "profile_adjustment_made": False,
            "adjustment_reason": "High defer history was noted in the rationale, but the tier was preserved because the remaining time and evidence did not justify escalation.",
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
            },
            "user_context": {
                "task_type_start_lead_hours": None,
                "entity_priority_multiplier": None,
                "entity_defer_rate": None,
                "entity_avg_start_lead_hours": None,
                "entity_observation_count": 0,
                "sender_response_rate": None,
                "sender_weight": None,
                "sender_observation_count": 0,
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
            },
        },
        "output": {
            "priority_tier": "MEDIUM",
            "action_window": "TODAY",
            "rationale": "Keep the pre-scored MEDIUM tier because there is not enough reliable history to personalize yet; the calendar says TODAY is a better fit than NOW.",
            "confidence": 0.78,
            "profile_adjustment_made": False,
            "adjustment_reason": "No profile-based adjustment was made because profile confidence and observation counts are too low.",
        },
    },
]


class PriorityReasoner:
    def __init__(self, settings: PipelineSettings, client: Any | None = None) -> None:
        self.settings = settings
        self.client = client

    def build_llm_input(
        self,
        *,
        task: CanonicalTask,
        profile: BehaviorProfile,
        onboarding: OnboardingContext,
        entity_context: EntityWeight | None,
        sender_context: SenderWeight | None,
        can_personalize: bool,
        current_hour: int | None = None,
    ) -> dict[str, Any]:
        timezone_name = onboarding.timezone or self.settings.provider_timezone_fallback
        now_hour = (
            current_hour
            if current_hour is not None
            else current_hour_for_timezone(timezone_name, fallback=self.settings.provider_timezone_fallback)
        )
        return {
            "task": {
                "type": task.task_type.value,
                "deadline_hours": task.deadline_hours,
                "entity_name": task.topic_entity.entity_name,
                "entity_type": task.topic_entity.entity_type.value,
                "platforms_seen": [platform.value for platform in task.platforms_seen],
                "signal_count": task.signal_count,
                "pre_scored_tier": task.priority_tier.value if task.priority_tier else PriorityTier.LOW.value,
                "score_reasons": task.score_reasons,
            },
            "user_context": {
                "task_type_start_lead_hours": profile.task_type_start_leads.get(task.task_type),
                "entity_priority_multiplier": entity_context.priority_multiplier if entity_context else None,
                "entity_defer_rate": entity_context.defer_rate if entity_context else None,
                "entity_avg_start_lead_hours": entity_context.avg_start_lead_hours if entity_context else None,
                "entity_observation_count": entity_context.observation_count if entity_context else 0,
                "sender_response_rate": sender_context.response_rate if sender_context else None,
                "sender_weight": sender_context.weight if sender_context else None,
                "sender_observation_count": sender_context.observation_count if sender_context else 0,
                "peak_action_hour": profile.peak_action_hour,
                "low_energy_hours": profile.low_energy_hours,
                "current_hour": now_hour,
                "profile_confidence": profile.confidence,
                "can_personalize": can_personalize,
            },
            "calendar_context": {
                "timezone": onboarding.timezone,
                "timetable_summary": onboarding.timetable_summary,
                "busy_windows": [window.model_dump(mode="json") for window in onboarding.busy_windows],
                "recurring_task_notes": onboarding.recurring_task_notes,
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

        output = self._call_openai(request_payload)
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

    def _call_openai(self, request_payload: dict[str, Any]) -> StructuredLlmOutput:
        api_key = os.environ.get("OPENAI_API_KEY") or load_dotenv_value("OPENAI_API_KEY")
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
                    "anyOf": [
                        {"type": "string"},
                        {"type": "null"},
                    ]
                },
            },
            "required": [
                "priority_tier",
                "action_window",
                "rationale",
                "confidence",
                "profile_adjustment_made",
                "adjustment_reason",
            ],
        }

    def _fallback_reasoning(self, llm_input: dict[str, Any]) -> StructuredLlmOutput:
        task = llm_input["task"]
        user = llm_input["user_context"]
        tier = PriorityTier(task["pre_scored_tier"])
        adjustment_reason = None
        adjusted = False

        if user["can_personalize"]:
            entity_multiplier = user.get("entity_priority_multiplier")
            sender_weight = user.get("sender_weight")
            task_type_lead = user.get("task_type_start_lead_hours")
            deadline_hours = task.get("deadline_hours")

            if deadline_hours is not None and task_type_lead is not None and deadline_hours < task_type_lead and tier != PriorityTier.CRITICAL:
                tier = self._raise_tier(tier)
                adjusted = True
                adjustment_reason = "Escalated because personal start-lead behavior shows the task is already inside the user's normal buffer."
            elif entity_multiplier is not None and entity_multiplier <= 0.75 and tier in {PriorityTier.HIGH, PriorityTier.MEDIUM}:
                tier = self._lower_tier(tier)
                adjusted = True
                adjustment_reason = "Lowered because recent entity-level behavior shows the user consistently defers this topic."
            elif sender_weight is not None and sender_weight >= 1.4 and tier != PriorityTier.CRITICAL:
                tier = self._raise_tier(tier)
                adjusted = True
                adjustment_reason = "Escalated because the user responds quickly to this sender."

        action_window = self._choose_action_window(task=task, user=user, calendar_context=llm_input["calendar_context"])
        rationale = self._build_rationale(task=task, user=user, action_window=action_window)
        confidence = 0.75 if user["can_personalize"] else max(0.45, user.get("profile_confidence", 0.0))

        return StructuredLlmOutput(
            priority_tier=tier,
            action_window=action_window,
            rationale=rationale,
            confidence=round(min(0.95, confidence), 2),
            profile_adjustment_made=adjusted,
            adjustment_reason=adjustment_reason,
        )

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
