# SerpAPI — `SERPAPI_KEY`

SerpAPI proxies Google / Bing / Scholar / News searches into a clean JSON API. Optional research clients may use it to augment web research without scraping. Free tier: 250 searches/month. Paid tiers start at $50/month for 5,000 searches.

## What you need

A 64-char lowercase-hex API key.

## Where to get it

1. Visit https://serpapi.com/users/sign_up
2. Sign up (email + password). SerpAPI also offers GitHub / Google OAuth signup — either works.
3. Verify email (link sent automatically).
4. After verification, visit https://serpapi.com/manage-api-key
5. The dashboard shows the key under **"Your Private API Key"**. Copy it — 64 hex chars, e.g., `f6852adc74c93a038d45562ba52958ef763e825d678f25a0aa47ce05dd40fba2`.

## Validation

Regex: `^[a-f0-9]{64}$`

Strictly lowercase hex, exactly 64 chars. If the user pastes:
- Uppercase chars → wrong key or wrong copy. SerpAPI keys are always lowercase.
- Wrong length → truncated paste; re-copy from the dashboard.
- Non-hex chars → likely they copied the surrounding HTML or a different field.

## Sanity check (recommended)

```bash
KEY="$( pbpaste )"
curl -sS "https://serpapi.com/search.json?engine=google&q=mcp+protocol&num=1&api_key=$KEY" \
  | head -c 300
unset KEY
```

Expected: JSON with `organic_results` array (1 entry). On 401, the key is wrong. On `error` field saying "Your account has run out of searches" → the user hit the free-tier limit; they need to upgrade or wait until next month.

**Discipline note**: putting the key in the URL query string echoes it into shell history. If the user is on a shared machine, prefer the heredoc + POST variant:

```bash
KEY="$( pbpaste )"
curl -sS -G "https://serpapi.com/search.json" \
  --data-urlencode "engine=google" \
  --data-urlencode "q=test" \
  --data-urlencode "api_key=$KEY" \
  --data-urlencode "num=1" \
  | head -c 300
unset KEY
```

Same end-effect; the key doesn't appear in `ps aux` mid-call.

## Target env vars + file

Target: **`claude_desktop_config.json` → `mcpServers.rka.env`** (the rka MCP server's deep-research path uses it).

```json
{
  "mcpServers": {
    "rka": {
      "command": "/Users/<you>/.local/bin/rka",
      "args": ["mcp"],
      "env": {
        "SERPAPI_KEY": "f6852adc74c93a038d45562ba52958ef763e825d678f25a0aa47ce05dd40fba2"
      }
    }
  }
}
```

## Restart instruction

```
✓ SERPAPI_KEY persisted.

Claude Desktop: fully quit (Cmd+Q) and reopen.
Verify by asking me to run a deep-research query that hits
SerpAPI under the hood. You should see results within a few
seconds and the SerpAPI dashboard's "Searches Used This
Month" counter should tick up by 1.

Free-tier reminder: 250 searches/month. The dashboard shows
remaining at https://serpapi.com/manage-api-key
```

## Common pitfalls

- **Free-tier limit consumed silently** — once you hit 250, calls return `error` in the JSON body but with HTTP 200. The user might think the key works while it actually doesn't return data. Watch for the dashboard's monthly counter.
- **Two separate accounts** — if the user has both a free SerpAPI account and a paid one (e.g., personal + work), confirm which one they're using. Different keys; different budgets.
- **Key rotation** — SerpAPI lets you regenerate keys via the dashboard. The old key is revoked instantly. If the user rotates, this walkthrough has to re-run for both targets.
