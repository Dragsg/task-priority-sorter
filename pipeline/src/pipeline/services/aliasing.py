from __future__ import annotations

from pipeline.models import EntityAlias, TopicEntity


class EntityAliasResolver:
    def resolve(self, entity: TopicEntity, aliases: dict[str, EntityAlias]) -> TopicEntity:
        alias = aliases.get(entity.entity_key)
        if alias is None:
            return entity
        return TopicEntity(
            entity_name=alias.canonical_entity_name,
            entity_type=alias.entity_type,
            entity_key=alias.canonical_entity_key,
        )
