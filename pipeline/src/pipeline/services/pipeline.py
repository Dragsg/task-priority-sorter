from __future__ import annotations

from pipeline.config import PipelineSettings
from pipeline.models import BehaviorProfile, FeedbackEvent, OnboardingContext
from pipeline.models.enums import EntityType, TaskType
from pipeline.services.aliasing import EntityAliasResolver
from pipeline.services.dedup import TaskDeduplicator
from pipeline.services.extraction import SignalExtractor
from pipeline.services.llm import PriorityReasoner
from pipeline.services.postprocess import PostProcessor
from pipeline.services.profile import ProfileService
from pipeline.services.scoring import PriorityScorer
from pipeline.storage.repositories import PipelineRepository, PipelineRunBundle


class PriorityPipeline:
    def __init__(
        self,
        repository: PipelineRepository,
        *,
        settings: PipelineSettings | None = None,
        extractor: SignalExtractor | None = None,
        deduplicator: TaskDeduplicator | None = None,
        scorer: PriorityScorer | None = None,
        profile_service: ProfileService | None = None,
        reasoner: PriorityReasoner | None = None,
        post_processor: PostProcessor | None = None,
        alias_resolver: EntityAliasResolver | None = None,
    ) -> None:
        self.settings = settings or PipelineSettings()
        self.repository = repository
        self.extractor = extractor or SignalExtractor(timezone_fallback=self.settings.provider_timezone_fallback)
        self.deduplicator = deduplicator or TaskDeduplicator(self.settings)
        self.scorer = scorer or PriorityScorer()
        self.profile_service = profile_service or ProfileService(self.settings)
        self.reasoner = reasoner or PriorityReasoner(self.settings)
        self.post_processor = post_processor or PostProcessor(self.settings)
        self.alias_resolver = alias_resolver or EntityAliasResolver()

    def run_for_user(self, user_id: str, *, limit: int | None = None) -> PipelineRunBundle:
        messages = self.repository.get_raw_messages(user_id, limit=limit)
        return self.run_messages(user_id, messages)

    def run_messages(self, user_id: str, messages) -> PipelineRunBundle:
        run_id = self.repository.create_run(user_id)
        try:
            profile = self.repository.get_behavior_profile(user_id) or self.profile_service.create_default_profile(user_id)
            onboarding = self.repository.get_onboarding_context(user_id) or OnboardingContext(user_id=user_id)
            aliases = self.repository.get_entity_aliases(user_id)

            signals = []
            for message in messages:
                signal = self.extractor.extract(message)
                signal = signal.model_copy(
                    update={
                        "run_id": run_id,
                        "topic_entity": self.alias_resolver.resolve(signal.topic_entity, aliases),
                    }
                )
                if not signal.has_task:
                    continue
                signals.append(signal)

            canonical_tasks = [self.scorer.score(task) for task in self.deduplicator.deduplicate(signals, run_id=run_id)]

            decisions = []
            task_cards = []
            for task in canonical_tasks:
                entity_context = profile.entity_weights.get(task.topic_entity.entity_key)
                sender_context = self._resolve_sender_context(profile, task)
                can_personalize = self.profile_service.can_personalize(
                    profile,
                    entity_observation_count=entity_context.observation_count if entity_context else 0,
                    sender_observation_count=sender_context.observation_count if sender_context else 0,
                )
                llm_input = self.reasoner.build_llm_input(
                    task=task,
                    profile=profile,
                    onboarding=onboarding,
                    entity_context=entity_context,
                    sender_context=sender_context,
                    can_personalize=can_personalize,
                )
                llm_output, decision = self.reasoner.reason_task(run_id=run_id, task=task, llm_input=llm_input)
                decisions.append(decision)
                task_cards.append(
                    self.post_processor.build_task_card(
                        run_id=run_id,
                        task=task,
                        llm_output=llm_output,
                        profile_version=profile.profile_version,
                    )
                )

            bundle = PipelineRunBundle(
                run_id=run_id,
                signals=signals,
                canonical_tasks=canonical_tasks,
                decisions=decisions,
                task_cards=task_cards,
                profile=profile,
            )
            self.repository.save_pipeline_results(bundle)
            self.repository.mark_run_finished(run_id)
            return bundle
        except Exception as exc:
            self.repository.mark_run_finished(run_id, error_text=str(exc))
            raise

    def apply_feedback(self, event: FeedbackEvent) -> BehaviorProfile:
        profile = self.repository.get_behavior_profile(event.user_id) or self.profile_service.create_default_profile(event.user_id)
        return self.apply_feedback_to_profile(profile, event)

    def apply_feedback_to_profile(self, profile: BehaviorProfile, event: FeedbackEvent) -> BehaviorProfile:
        updated = self.profile_service.update_from_feedback(profile, event)
        self.repository.save_feedback_profile_update(event, updated)
        return updated

    def register_manual_task(
        self,
        *,
        user_id: str,
        task_type: TaskType,
        entity_key: str,
        entity_name: str,
        entity_type: EntityType,
        deadline_hours: float | None,
    ) -> BehaviorProfile:
        profile = self.repository.get_behavior_profile(user_id) or self.profile_service.create_default_profile(user_id)
        updated = self.profile_service.update_from_manual_task(
            profile,
            task_type=task_type,
            entity_key=entity_key,
            entity_name=entity_name,
            entity_type=entity_type,
            deadline_hours=deadline_hours,
        )
        self.repository.save_behavior_profile(updated)
        return updated

    def _resolve_sender_context(self, profile: BehaviorProfile, task) -> object | None:
        for sender_id in task.sender_ids:
            sender_hash = self.profile_service.hash_identity(user_salt=profile.user_salt, identifier=sender_id)
            sender_context = profile.sender_weights.get(sender_hash)
            if sender_context is not None:
                return sender_context
        return None
