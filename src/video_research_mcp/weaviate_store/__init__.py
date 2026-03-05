"""Write-through store functions — one per Weaviate collection.

Each store_* function is called by its corresponding tool after a
successful Gemini response. All writes are fire-and-forget: failures
log a warning but never propagate to the tool caller.

Re-exports all store functions so existing imports like
``from .weaviate_store import store_video_analysis`` keep working.
"""

from .calls import store_call_notes
from .community import store_community_reaction
from .deep_research import store_deep_research, store_deep_research_followup
from .concepts import store_concept_knowledge, store_relationship_edges
from .content import store_content_analysis
from .research import store_evidence_assessment, store_research_finding, store_research_plan
from .search import store_web_search
from .session import store_session_turn
from .video import store_video_analysis, store_video_metadata

__all__ = [
    "store_call_notes",
    "store_deep_research",
    "store_deep_research_followup",
    "store_community_reaction",
    "store_concept_knowledge",
    "store_content_analysis",
    "store_evidence_assessment",
    "store_relationship_edges",
    "store_research_finding",
    "store_research_plan",
    "store_session_turn",
    "store_video_analysis",
    "store_video_metadata",
    "store_web_search",
]
