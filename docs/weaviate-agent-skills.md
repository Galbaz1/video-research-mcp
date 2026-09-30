# Introducing Weaviate Agent Skills

This is a source note about Weaviate's agent-skills release, not documentation
for the knowledge tools bundled with video-research-mcp. For this repository's
setup, collections and tool behavior, use the
[Knowledge Store guide](tutorials/KNOWLEDGE_STORE.md).

The original article was published on **February 18, 2026** with a six-minute
reading estimate and was captured through Jina MCP (`mcp__jina__read_url`). Its
authors were Femke Plantinga (Team Lead Growth), Prajjwal Yadav (Developer
Advocate Intern) and Victoria Slocum (Machine Learning Engineer).
[Read the source article](https://weaviate.io/blog/weaviate-agent-skills) or
[visit its repository](https://github.com/weaviate/agent-skills).

## Overview

The article introduced skills intended to give coding agents more specific
Weaviate guidance, including collection schemas, ingestion and retrieval. It
described two areas: focused operations under `/skills/weaviate` and application
cookbooks under `/skills/weaviate-cookbooks/`. This is the article's dated
inventory; installed commands and capabilities can differ by version.

## Weaviate Skill

The operations skill covered schema inspection, collection creation, metadata,
CSV/JSON/JSONL imports, hybrid/semantic/keyword retrieval, and Query Agent
questions or searches. The article illustrated these through natural-language
requests such as creating a product collection or finding similar products.
Its `/weaviate:data` and `/weaviate:quickstart` commands belonged to that separate
plugin, not this MCP server.

## Cookbooks

The article's application examples included a Query Agent chatbot with FastAPI
and an optional Next.js frontend, multivector PDF retrieval with embeddings and
Ollama generation, several RAG patterns, and DSPy tool-calling agents. These
were external blueprints, not shipped video-research-mcp applications.

Historical example prompts:

```text
/weaviate-cookbooks build a query agent chatbot with a frontend
/weaviate-cookbooks build a multivector pdf application
/weaviate-cookbooks build a RAG application
```

## Commands

The article listed six Claude Code plugin commands:

| Command | Purpose described in the article |
| --- | --- |
| Ask | Generate an answer with sources through Query Agent ask mode |
| Collections | List collections or inspect a collection schema |
| Explore | Inspect samples and property metrics |
| Fetch | Retrieve objects by ID or filters |
| Query | Retrieve objects through Query Agent search mode |
| Search | Use explicit hybrid, semantic or keyword retrieval |

### Example Usage

These examples retain the separate plugin's syntax from the article. Check that
plugin's installed documentation before running them:

```text
/weaviate:ask query "What are the benefits of vector databases?" collections "Documentation"
/weaviate:collections
/weaviate:collections name "Articles"
/weaviate:explore "Products" limit 10
/weaviate:fetch collection "Articles" id "UUID"
/weaviate:fetch collection "Articles" filters '{"property": "category", "operator": "equal", "value": "Science"}'
/weaviate:query query "machine learning tutorials" collections "Articles,BlogPosts" limit 5
/weaviate:search query "product SKU-123" collection "Products" type "keyword"
/weaviate:search query "similar items" collection "Products" type "semantic"
/weaviate:search query "best laptops" collection "Products" type "hybrid" alpha "0.7"
```

In this repository, the closest operations are `knowledge_schema`,
`knowledge_fetch`, `knowledge_search` and `knowledge_ask`. Their arguments and
response shapes differ. In particular, this repository's `knowledge_query` is
deprecated in favor of `knowledge_search`; that does not rename or deprecate the
external plugin's `/weaviate:query` command.

## Get Started

The article gave these installation options:

```text
npx skills add weaviate/agent-skills
/plugin marketplace add weaviate/agent-skills
/plugin install weaviate@weaviate-plugins
```

It also directed readers to [Weaviate Cloud](https://console.weaviate.cloud),
`WEAVIATE_URL`, `WEAVIATE_API_KEY` and `/weaviate:quickstart`. Those instructions
are retained as historical examples. This note does not verify a current install,
cluster entitlement, provider access or command availability.

## Images Referenced

The source article supplied [a hero image](https://weaviate.io/assets/images/hero-862bd4553db8536784d06e92bb2ce4f7.jpg)
and [a skills structure diagram](https://weaviate.io/assets/images/agent-skills-diagram-99c7f094074dc5b25b19a22ce758e67e.png),
plus author portraits for [Femke](https://weaviate.io/img/people/icon/femke.jpg),
[Prajjwal](https://weaviate.io/img/people/icon/prajjwal.jpg) and
[Victoria](https://weaviate.io/img/people/icon/victoria.jpg).

Original article tags: `release`, `agents`.
