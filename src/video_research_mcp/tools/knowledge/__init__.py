"""Knowledge query tools — 8 tools on a FastMCP sub-server."""

from fastmcp import FastMCP

knowledge_server = FastMCP("knowledge")

# Import tool modules to register their @knowledge_server.tool() decorators
from . import search as _search  # noqa: F401, E402
from . import retrieval as _retrieval  # noqa: F401, E402
from . import ingest as _ingest  # noqa: F401, E402
from . import agent as _agent  # noqa: F401, E402
from . import schema as _schema  # noqa: F401, E402

# Re-export tool functions for backward-compatible imports
from .search import knowledge_search  # noqa: F401, E402
from .retrieval import knowledge_related, knowledge_stats, knowledge_fetch  # noqa: F401, E402
from .ingest import knowledge_ingest  # noqa: F401, E402
from .agent import knowledge_ask, knowledge_query  # noqa: F401, E402
from .schema import knowledge_schema  # noqa: F401, E402
