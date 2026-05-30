# Semantic Scholar — `SEMANTIC_SCHOLAR_API_KEY`

The RKA MCP server's `rka_search_semantic_scholar` tool can call Semantic Scholar anonymously (rate-limited: 100 req per 5 min, shared globally), or with an API key (rate-limited: 1 req/sec per key — much more usable for batch lookups). The key is free; the user requests it via a form.

## What you need

One API key, currently issued as 32–48 chars of alphanumeric. Common prefix: `s2k-` (but not required — Semantic Scholar has issued keys without the prefix historically).

## Where to get it

1. Visit https://www.semanticscholar.org/product/api#api-key-form
2. Fill out the form:
   - Name + email + organization
   - **Intended use**: brief description (e.g., "Personal research assistant for literature review and citation graph navigation" — short and honest is fine)
   - Check the terms-of-use checkbox
3. Submit. Semantic Scholar reviews requests manually; turnaround is usually 1–3 business days, occasionally same-day.
4. When approved, an email arrives with the key. Copy it.

If the user submitted the form some time ago and didn't get a response, they should check spam first, then re-submit if there's no record. There's no online status portal.

## Validation

Regex: `^(s2k-)?[A-Za-z0-9]{28,48}$`

The `s2k-` prefix is optional. Reject if too short or contains non-alphanumeric (apart from the prefix's hyphen).

## Sanity check (recommended)

```bash
KEY="$( pbpaste )"
curl -sS -H "x-api-key: $KEY" \
  "https://api.semanticscholar.org/graph/v1/paper/search?query=mcp&limit=1" \
  | head -c 200
unset KEY
```

Expected: JSON with `total` and `data` fields. 401 means the key is wrong; 429 means you hit the rate limit (shouldn't happen on a single request with a fresh key).

## Target env vars + file

Target: **`claude_desktop_config.json` → `mcpServers.rka.env`** (the rka MCP server reads this).

If the orchestrator daemon is installed, **also** persist to **`orchestrator/.env`**. The daemon's SDK subprocess passes this env to the `rka mcp` child it spawns; without it the Brain's `rka_search_semantic_scholar` calls fall back to anonymous rate limits.

```json
{
  "mcpServers": {
    "rka": {
      "command": "/Users/<you>/.local/bin/rka",
      "args": ["mcp"],
      "env": {
        "SEMANTIC_SCHOLAR_API_KEY": "s2k-<key>"
      }
    }
  }
}
```

## Restart instruction

```
✓ SEMANTIC_SCHOLAR_API_KEY persisted.

Claude Desktop: fully quit (Cmd+Q) and reopen.
RKA orchestrator: docker compose -f docker-compose.yml \
                                 -f orchestrator/docker-compose.yml \
                                 up -d --force-recreate

Verify in a Claude Desktop conversation by asking:
  "Search Semantic Scholar for 'graph neural networks on protein structures'"

If you see results within ~1 second, the key is active. If
you see a 429 rate-limit error, anonymous mode is still in
effect — restart wasn't picked up.
```

## Common pitfalls

- **Key approval pending** — the form turnaround is variable. If you're walking the user through this and they don't have a key yet, defer the persist step until they receive one. There's no point setting a placeholder.
- **Multiple keys** — Semantic Scholar allows multiple keys per user but doesn't surface them on a dashboard. If the user has issued keys previously and lost track, the cleanest fix is requesting a new one (the old ones don't auto-revoke; that's a Semantic Scholar limitation).
- **Used by both `claude_desktop_config.json` AND `orchestrator/.env`** — easy to set in one and forget the other, leading to "it works in Claude Desktop but the orchestrator's Brain still gets rate-limited". Always set both if RKA is installed.
