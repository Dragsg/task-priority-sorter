from __future__ import annotations

from pipeline.models import CanonicalTask, PriorityTier, SenderRole, TaskType


class PriorityScorer:
    def score(self, task: CanonicalTask) -> CanonicalTask:
        score = 0
        reasons: list[str] = []

        hours = task.deadline_hours
        if hours is not None:
            if hours < 6:
                score += 40
                reasons.append("deadline under 6 hours")
            elif hours < 24:
                score += 30
                reasons.append("deadline under 24 hours")
            elif hours < 72:
                score += 15
                reasons.append("deadline within 3 days")
            else:
                score += 5

        if SenderRole.LECTURER in task.sender_roles:
            score += 20
            reasons.append("from lecturer")
        elif SenderRole.INSTITUTION in task.sender_roles:
            score += 15
            reasons.append("from institution")
        elif SenderRole.PEER in task.sender_roles:
            score += 5
            reasons.append("from peer")

        if task.signal_count >= 3:
            score += 15
            reasons.append(f"mentioned {task.signal_count} times across platforms")
        elif task.signal_count == 2:
            score += 7
            reasons.append("repeated signal across sources")

        if task.task_type == TaskType.SUBMISSION:
            score += 15
            reasons.append("graded submission")
        elif task.task_type == TaskType.MEETING:
            score += 10
            reasons.append("scheduled meeting")
        elif task.task_type == TaskType.READING:
            score += 3
            reasons.append("reading task")

        if task.urgency_word_count:
            score += min(task.urgency_word_count * 3, 10)
            reasons.append("urgent language detected")

        if score >= 70:
            tier = PriorityTier.CRITICAL
        elif score >= 45:
            tier = PriorityTier.HIGH
        elif score >= 25:
            tier = PriorityTier.MEDIUM
        else:
            tier = PriorityTier.LOW

        return task.model_copy(update={"priority_score": score, "priority_tier": tier, "score_reasons": reasons})
