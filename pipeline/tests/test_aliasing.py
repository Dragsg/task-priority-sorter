from pipeline.models import EntityAlias, TopicEntity
from pipeline.models.enums import EntityType
from pipeline.services.aliasing import EntityAliasResolver


def test_alias_resolution_maps_to_canonical_entity():
    resolver = EntityAliasResolver()
    entity = TopicEntity(entity_name="NUS Computing Club", entity_type=EntityType.CCA, entity_key="nus computing club")
    aliases = {
        "nus computing club": EntityAlias(
            alias_key="nus computing club",
            canonical_entity_key="computing club",
            canonical_entity_name="Computing Club",
            entity_type=EntityType.CCA,
        )
    }

    resolved = resolver.resolve(entity, aliases)

    assert resolved.entity_key == "computing club"
    assert resolved.entity_name == "Computing Club"
