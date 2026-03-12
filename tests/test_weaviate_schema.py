"""Tests for Weaviate schema definitions."""

from __future__ import annotations

from video_research_mcp.weaviate_schema import (
    ALL_COLLECTIONS,
    CALL_NOTES,
    COMMUNITY_REACTIONS,
    CONCEPT_KNOWLEDGE,
    CONTENT_ANALYSES,
    DEEP_RESEARCH_REPORTS,
    RELATIONSHIP_EDGES,
    RESEARCH_FINDINGS,
    RESEARCH_PLANS,
    VIDEO_ANALYSES,
    VIDEO_METADATA,
    CollectionDef,
    PropertyDef,
)


class TestCollectionDefinitions:
    """Verify all 12 collections are defined correctly."""

    def test_all_collections_count(self):
        """ALL_COLLECTIONS contains exactly 12 collections."""
        assert len(ALL_COLLECTIONS) == 12

    def test_collection_names(self):
        """All expected collection names are present."""
        names = {c.name for c in ALL_COLLECTIONS}
        expected = {
            "ResearchFindings", "VideoAnalyses", "ContentAnalyses",
            "VideoMetadata", "SessionTranscripts", "WebSearchResults", "ResearchPlans",
            "CommunityReactions", "ConceptKnowledge", "RelationshipEdges", "CallNotes",
            "DeepResearchReports",
        }
        assert names == expected

    def test_every_collection_has_created_at(self):
        """Every collection includes a created_at date property."""
        for col in ALL_COLLECTIONS:
            prop_names = [p.name for p in col.properties]
            assert "created_at" in prop_names, f"{col.name} missing created_at"

    def test_every_collection_has_source_tool(self):
        """Every collection includes a source_tool text property."""
        for col in ALL_COLLECTIONS:
            prop_names = [p.name for p in col.properties]
            assert "source_tool" in prop_names, f"{col.name} missing source_tool"


class TestNewProperties:
    """Verify the 18 new properties are defined in the correct collections."""

    def test_video_analyses_has_new_properties(self):
        """VideoAnalyses has timestamps_json, topics, sentiment."""
        names = {p.name for p in VIDEO_ANALYSES.properties}
        assert "timestamps_json" in names
        assert "topics" in names
        assert "sentiment" in names

    def test_research_findings_has_new_properties(self):
        """ResearchFindings has supporting, contradicting, methodology_critique, recommendations, report_uuid."""
        names = {p.name for p in RESEARCH_FINDINGS.properties}
        for prop in ("supporting", "contradicting", "methodology_critique", "recommendations", "report_uuid"):
            assert prop in names, f"Missing {prop}"

    def test_content_analyses_has_new_properties(self):
        """ContentAnalyses has structure_notes, quality_assessment."""
        names = {p.name for p in CONTENT_ANALYSES.properties}
        assert "structure_notes" in names
        assert "quality_assessment" in names

    def test_video_metadata_has_new_properties(self):
        """VideoMetadata has 7 new properties."""
        names = {p.name for p in VIDEO_METADATA.properties}
        for prop in ("channel_id", "comment_count", "duration_seconds", "category",
                      "definition", "has_captions", "default_language"):
            assert prop in names, f"Missing {prop}"

    def test_research_plans_has_recommended_models(self):
        """ResearchPlans has recommended_models_json."""
        names = {p.name for p in RESEARCH_PLANS.properties}
        assert "recommended_models_json" in names

    def test_new_vectorization_flags(self):
        """New semantic fields are vectorized, metadata fields are not."""
        # Vectorized
        for name in ("supporting", "contradicting", "methodology_critique", "recommendations"):
            prop = next(p for p in RESEARCH_FINDINGS.properties if p.name == name)
            assert not prop.skip_vectorization, f"{name} should be vectorized"
        # Not vectorized
        prop = next(p for p in RESEARCH_FINDINGS.properties if p.name == "report_uuid")
        assert prop.skip_vectorization
        prop = next(p for p in VIDEO_ANALYSES.properties if p.name == "timestamps_json")
        assert prop.skip_vectorization
        prop = next(p for p in VIDEO_ANALYSES.properties if p.name == "sentiment")
        assert prop.skip_vectorization


class TestReferences:
    """Verify cross-reference definitions."""

    def test_video_analyses_has_metadata_reference(self):
        """VideoAnalyses has a has_metadata reference to VideoMetadata."""
        assert len(VIDEO_ANALYSES.references) == 1
        ref = VIDEO_ANALYSES.references[0]
        assert ref.name == "has_metadata"
        assert ref.target_collection == "VideoMetadata"

    def test_research_findings_has_report_reference(self):
        """ResearchFindings has a belongs_to_report self-reference."""
        assert len(RESEARCH_FINDINGS.references) == 1
        ref = RESEARCH_FINDINGS.references[0]
        assert ref.name == "belongs_to_report"
        assert ref.target_collection == "ResearchFindings"

    def test_community_reactions_has_video_reference(self):
        """CommunityReactions has a for_video reference to VideoMetadata."""
        assert len(COMMUNITY_REACTIONS.references) == 1
        ref = COMMUNITY_REACTIONS.references[0]
        assert ref.name == "for_video"
        assert ref.target_collection == "VideoMetadata"

    def test_collections_without_references(self):
        """Most collections have no references."""
        has_refs = {"VideoAnalyses", "ResearchFindings", "CommunityReactions", "DeepResearchReports"}
        for col in ALL_COLLECTIONS:
            if col.name not in has_refs:
                assert len(col.references) == 0, f"{col.name} should have no references"


class TestToDict:
    """Verify to_dict() produces valid Weaviate-compatible structures."""

    def test_to_dict_has_class_key(self):
        """to_dict() uses 'class' key (not 'name') for Weaviate compatibility."""
        for col in ALL_COLLECTIONS:
            d = col.to_dict()
            assert "class" in d
            assert d["class"] == col.name

    def test_to_dict_has_properties(self):
        """to_dict() includes properties list."""
        for col in ALL_COLLECTIONS:
            d = col.to_dict()
            assert "properties" in d
            assert isinstance(d["properties"], list)
            assert len(d["properties"]) > 0

    def test_property_dict_structure(self):
        """Each property dict has name and dataType keys."""
        for col in ALL_COLLECTIONS:
            d = col.to_dict()
            for prop in d["properties"]:
                assert "name" in prop
                assert "dataType" in prop


class TestVectorizeFlags:
    """Verify skip_vectorization flags are correct."""

    def test_created_at_skips_vectorization(self):
        """created_at should skip vectorization in all collections."""
        for col in ALL_COLLECTIONS:
            prop = next(p for p in col.properties if p.name == "created_at")
            assert prop.skip_vectorization is True, f"{col.name}.created_at should skip"

    def test_source_tool_skips_vectorization(self):
        """source_tool should skip vectorization in all collections."""
        for col in ALL_COLLECTIONS:
            prop = next(p for p in col.properties if p.name == "source_tool")
            assert prop.skip_vectorization is True, f"{col.name}.source_tool should skip"

    def test_research_findings_vectorized_fields(self):
        """ResearchFindings vectorizes claim, reasoning, executive_summary."""
        vectorized = [
            p.name for p in RESEARCH_FINDINGS.properties if not p.skip_vectorization
        ]
        assert "claim" in vectorized
        assert "reasoning" in vectorized
        assert "executive_summary" in vectorized

    def test_video_analyses_vectorized_fields(self):
        """VideoAnalyses vectorizes title, summary, key_points, topics."""
        vectorized = [
            p.name for p in VIDEO_ANALYSES.properties if not p.skip_vectorization
        ]
        assert "title" in vectorized
        assert "summary" in vectorized
        assert "key_points" in vectorized
        assert "topics" in vectorized

    def test_skip_vectorization_in_dict(self):
        """Properties with skip=True include moduleConfig in to_dict()."""
        prop = next(p for p in RESEARCH_FINDINGS.properties if p.name == "created_at")
        d = prop.to_dict()
        assert "moduleConfig" in d
        assert d["moduleConfig"]["text2vec-openai"]["skip"] is True

    def test_no_skip_vectorization_in_dict(self):
        """Properties with skip=False do NOT include moduleConfig."""
        prop = next(p for p in RESEARCH_FINDINGS.properties if p.name == "claim")
        d = prop.to_dict()
        assert "moduleConfig" not in d


class TestIndexFlags:
    """Verify index_filterable, index_range_filters, index_searchable flags."""

    def test_created_at_has_range_index(self):
        """created_at should have index_range_filters=True in all collections."""
        for col in ALL_COLLECTIONS:
            prop = next(p for p in col.properties if p.name == "created_at")
            assert prop.index_range_filters is True, f"{col.name}.created_at needs range index"

    def test_updated_at_has_range_index(self):
        """updated_at should have index_range_filters=True in all collections."""
        for col in ALL_COLLECTIONS:
            prop = next(p for p in col.properties if p.name == "updated_at")
            assert prop.index_range_filters is True, f"{col.name}.updated_at needs range index"

    def test_numeric_fields_have_range_index(self):
        """All int/number fields that are filterable should have range indexes."""
        expected_range = {
            "VideoMetadata": {"view_count", "like_count", "comment_count", "duration_seconds"},
            "ResearchFindings": {"confidence"},
            "SessionTranscripts": {"turn_index"},
            "CommunityReactions": {"comment_count", "sentiment_positive", "sentiment_negative", "sentiment_neutral"},
        }
        for col in ALL_COLLECTIONS:
            range_props = expected_range.get(col.name, set())
            for prop in col.properties:
                if prop.name in range_props:
                    assert prop.index_range_filters is True, (
                        f"{col.name}.{prop.name} should have range index"
                    )

    def test_json_fields_not_searchable(self):
        """JSON blob text fields should have index_searchable=False."""
        json_fields = {
            "VideoAnalyses": {"raw_result", "timestamps_json"},
            "ContentAnalyses": {"raw_result"},
            "WebSearchResults": {"sources_json"},
            "ResearchPlans": {"phases_json", "recommended_models_json"},
        }
        for col in ALL_COLLECTIONS:
            field_names = json_fields.get(col.name, set())
            for prop in col.properties:
                if prop.name in field_names:
                    assert prop.index_searchable is False, (
                        f"{col.name}.{prop.name} should not be BM25 searchable"
                    )

    def test_id_fields_not_searchable(self):
        """ID and metadata text fields should have index_searchable=False."""
        id_fields = {
            "VideoAnalyses": {"video_id", "source_url", "sentiment"},
            "VideoMetadata": {"video_id", "channel_id", "duration", "published_at", "definition", "default_language"},
            "ContentAnalyses": {"source"},
            "SessionTranscripts": {"session_id"},
            "ResearchFindings": {"scope", "evidence_tier", "report_uuid"},
            "ResearchPlans": {"scope"},
        }
        for col in ALL_COLLECTIONS:
            field_names = id_fields.get(col.name, set())
            for prop in col.properties:
                if prop.name in field_names:
                    assert prop.index_searchable is False, (
                        f"{col.name}.{prop.name} should not be BM25 searchable"
                    )

    def test_source_tool_not_searchable_everywhere(self):
        """source_tool should have index_searchable=False in all collections."""
        for col in ALL_COLLECTIONS:
            prop = next(p for p in col.properties if p.name == "source_tool")
            assert prop.index_searchable is False, f"{col.name}.source_tool should not be searchable"

    def test_semantic_fields_use_default_searchable(self):
        """Vectorized text fields should have index_searchable=None (Weaviate default)."""
        for prop in RESEARCH_FINDINGS.properties:
            if prop.name in ("topic", "claim", "reasoning", "executive_summary"):
                assert prop.index_searchable is None, f"{prop.name} should use default searchable"

    def test_all_properties_are_filterable(self):
        """All properties should have index_filterable=True (default)."""
        for col in ALL_COLLECTIONS:
            for prop in col.properties:
                assert prop.index_filterable is True, (
                    f"{col.name}.{prop.name} should be filterable"
                )


class TestNewCollections:
    """Verify properties of the 4 new collections."""

    def test_community_reactions_properties(self):
        """CommunityReactions has expected properties."""
        names = {p.name for p in COMMUNITY_REACTIONS.properties}
        for prop in ("video_id", "video_title", "comment_count",
                      "sentiment_positive", "sentiment_negative", "sentiment_neutral",
                      "themes_positive", "themes_critical", "consensus", "notable_opinions_json"):
            assert prop in names, f"CommunityReactions missing {prop}"

    def test_concept_knowledge_properties(self):
        """ConceptKnowledge has expected properties."""
        names = {p.name for p in CONCEPT_KNOWLEDGE.properties}
        for prop in ("concept_name", "state", "source_url", "source_title",
                      "source_category", "description", "timestamp"):
            assert prop in names, f"ConceptKnowledge missing {prop}"

    def test_relationship_edges_properties(self):
        """RelationshipEdges has expected properties."""
        names = {p.name for p in RELATIONSHIP_EDGES.properties}
        for prop in ("from_concept", "to_concept", "relationship_type",
                      "source_url", "source_category"):
            assert prop in names, f"RelationshipEdges missing {prop}"

    def test_call_notes_properties(self):
        """CallNotes has expected properties."""
        names = {p.name for p in CALL_NOTES.properties}
        for prop in ("video_id", "source_url", "title", "summary",
                      "participants", "decisions", "action_items",
                      "topics_discussed", "duration", "meeting_date"):
            assert prop in names, f"CallNotes missing {prop}"

    def test_updated_at_in_all_collections(self):
        """Every collection includes an updated_at date property."""
        for col in ALL_COLLECTIONS:
            prop_names = [p.name for p in col.properties]
            assert "updated_at" in prop_names, f"{col.name} missing updated_at"

    def test_allowed_properties_includes_all_12(self):
        """ALLOWED_PROPERTIES auto-derived from ALL_COLLECTIONS includes all 12."""
        from video_research_mcp.tools.knowledge.helpers import ALLOWED_PROPERTIES
        assert len(ALLOWED_PROPERTIES) == 12
        for col in ALL_COLLECTIONS:
            assert col.name in ALLOWED_PROPERTIES, f"{col.name} missing from ALLOWED_PROPERTIES"


class TestVectorizedProperties:
    """Verify vectorized_properties() returns correct property lists."""

    def test_excludes_skip_vectorization_fields(self):
        """Properties with skip_vectorization=True are excluded."""
        col = CollectionDef(
            name="Test",
            properties=[
                PropertyDef("title", ["text"], "Title"),
                PropertyDef("metadata", ["text"], "Meta", skip_vectorization=True),
                PropertyDef("summary", ["text"], "Summary"),
            ],
        )
        result = col.vectorized_properties()
        assert "title" in result
        assert "summary" in result
        assert "metadata" not in result

    def test_excludes_non_text_types(self):
        """Non-text types (int, number, boolean, date) are excluded."""
        col = CollectionDef(
            name="Test",
            properties=[
                PropertyDef("title", ["text"], "Title"),
                PropertyDef("count", ["int"], "Count"),
                PropertyDef("score", ["number"], "Score"),
                PropertyDef("active", ["boolean"], "Active"),
                PropertyDef("created_at", ["date"], "Date", skip_vectorization=True),
            ],
        )
        result = col.vectorized_properties()
        assert result == ["title"]

    def test_includes_text_arrays(self):
        """text[] properties with skip_vectorization=False are included."""
        col = CollectionDef(
            name="Test",
            properties=[
                PropertyDef("tags", ["text[]"], "Tags"),
                PropertyDef("ids", ["text[]"], "IDs", skip_vectorization=True),
            ],
        )
        result = col.vectorized_properties()
        assert "tags" in result
        assert "ids" not in result

    def test_research_findings_spot_check(self):
        """ResearchFindings vectorized_properties includes semantic fields, excludes metadata."""
        result = RESEARCH_FINDINGS.vectorized_properties()
        for name in ("claim", "reasoning", "executive_summary", "topic",
                      "supporting", "contradicting", "methodology_critique", "recommendations"):
            assert name in result, f"{name} should be vectorized"
        for name in ("scope", "evidence_tier", "report_uuid", "open_questions"):
            assert name not in result, f"{name} should NOT be vectorized"

    def test_deep_research_spot_check(self):
        """DeepResearchReports vectorized_properties includes text, excludes JSON blobs."""
        result = DEEP_RESEARCH_REPORTS.vectorized_properties()
        for name in ("topic", "report_text"):
            assert name in result, f"{name} should be vectorized"
        for name in ("sources_json", "usage_json", "follow_ups_json"):
            assert name not in result, f"{name} should NOT be vectorized"
