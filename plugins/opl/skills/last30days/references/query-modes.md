# Query modes

Read this reference only for comparison or recommendation requests.

## Comparison

Resolve each entity independently. Do not give the first entity rich targeting
and let peers fall back to bare names.

The first entity uses the ordinary outer targeting flags. Put each peer's
verified targeting in a competitors-plan file:

```json
{
  "Peer B": {
    "x_handle": "peer_b",
    "subreddits": ["PeerB", "category"],
    "github_repos": ["owner/peer-b"],
    "context": "current disambiguating context"
  },
  "Peer C": {
    "x_handle": "peer_c",
    "subreddits": ["PeerC", "category"]
  }
}
```

Create a private temporary directory, write the JSON with Codex's file-editing
capability, validate it, then append its path:

```bash
COMPETITORS_DIR=$(mktemp -d "${TMPDIR:-/tmp}/last30days-competitors.XXXXXX")
chmod 700 "$COMPETITORS_DIR"
COMPETITORS_FILE="$COMPETITORS_DIR/competitors.json"
ENGINE_ARGS+=(--competitors-plan "$COMPETITORS_FILE")
```

Delete the temporary directory after the run.

Invoke the engine once with the full `A vs B [vs C]` topic. Use the engine's
reported comparison artifact set as the authority for saved paths.

In synthesis, compare like-for-like evidence and current first-party
positioning. State when an entity has materially thinner evidence. A difference
in retrieval volume is not itself a product advantage.

## Recommendations

Rank recommendations by evidence quality rather than raw mention count:

1. Specific practitioner experience or switching evidence
2. Measurable outcomes and current production adoption
3. Reasoned comparisons with explicit tradeoffs
4. Independent convergence across communities
5. Descriptive mentions

Treat promotional/course content as weak evidence. Separate options that are
merely present in the corpus from options people actually recommend. State the
use case and tradeoff for each top pick, and keep an option out of the ranking
when the evidence cannot defend it.
