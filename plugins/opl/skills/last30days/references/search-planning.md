# Web research and query planning

Search the web for the identity and context facts below. Do not require or name
a particular search tool, MCP server, connector, skill, or callable interface.
The bundled engine is still required for the research corpus.

## Resolve the topic

Use two to four focused searches. Resolve only fields that apply:

- Official X handle for a person, product, company, or creator
- Closely related X handles when they materially improve recall
- GitHub user for a person who ships code
- GitHub repository for a software product or project
- Dedicated and broad subreddits
- Current first-party positioning for a company, product, or service
- Current event context needed to disambiguate the topic

Prefer first-party profiles, official sites, and direct repositories. Verify
common-name matches before passing them to the engine. Never fabricate a handle
or repository to fill a flag.

For product topics, include relevant cross-product communities rather than
only brand-owned communities. The engine's category resolver owns the canonical
peer mapping; do not duplicate that table in the skill instructions.

For non-Latin or mixed-script topics, preserve the original name and add a
useful English transliteration or domain anchor when available. Do not assume
English-dominant communities will cover the topic.

## Build the query plan

Generate one to four subqueries. Each subquery has a concise platform-style
`search_query`, a natural-language `ranking_query`, applicable sources, and a
weight.

```json
{
  "intent": "opinion",
  "freshness_mode": "balanced_recent",
  "cluster_mode": "debate",
  "subqueries": [
    {
      "label": "primary",
      "search_query": "example product category",
      "ranking_query": "What are users saying about Example Product this month?",
      "sources": ["reddit", "x", "youtube", "hackernews", "github", "grounding"],
      "weight": 1.0
    }
  ]
}
```

Include only sources that doctor reports as ready or degraded with a usable
backend. Plan source names are exactly `reddit`, `x`, `youtube`, `tiktok`,
`hackernews`, `polymarket`, `github`, and `grounding`. Doctor labels the
`grounding` source as `web`; map that label explicitly. Keep product and person
disambiguators in every subquery when a name is collision-prone. Do not put
dates, `last 30 days`, `recent`, `news`, or other retrieval meta-language in
`search_query`; the engine owns the date window.

Map intent to plan shape:

- Breaking news: `strict_recent`, `story`
- Comparison or contested recommendation: `balanced_recent`, `debate`
- How-to/workflow: `evergreen_ok`, `workflow`
- Prediction: `strict_recent`, `market`
- General: `balanced_recent`, `none`

Create a temporary file, write the exact JSON with Codex's file-editing
capability, and pass its path rather than embedding JSON in a shell argument:

```bash
PLAN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/last30days-plan.XXXXXX")
chmod 700 "$PLAN_DIR"
PLAN_FILE="$PLAN_DIR/query-plan.json"
ENGINE_ARGS+=(--plan "$PLAN_FILE")
```

Delete the temporary directory after the run. Do not wrap the command in a
nested shell.

## Append resolved targeting

Append only non-empty values:

- `--x-handle=<handle>`
- `--x-related=<handle1,handle2>`
- `--github-user=<user>`
- `--github-repo=<owner/repo[,owner/repo]>`
- `--subreddits=<broad1,broad2>`
- `--dedicated-subreddits=<topic-home1,topic-home2>`
- `--tiktok-hashtags=<tag1,tag2>`
- `--tiktok-creators=<creator1,creator2>`

Do not suppress the engine's general-web path merely because web research was
used for planning. The engine should retain its normal source coverage unless
the user explicitly narrows `--search`.

Before invoking the engine, verify that the plan file is valid JSON and that
every supplied identity flag was verified during this run.
