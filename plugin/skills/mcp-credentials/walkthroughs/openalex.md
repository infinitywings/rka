# OpenAlex — `OPENALEX_MAILTO`

OpenAlex (the open citation graph from OurResearch) is free and unauthenticated. There's no API key. But if you set `OPENALEX_MAILTO=<your-email>`, OpenAlex routes you to their **polite pool**: same data, but a substantially higher rate limit and prioritized request handling.

**This is the only walkthrough in this skill where the "credential" is not a secret — it's just an email address.** Treat it accordingly: no need to mask it in diffs, no need for `pbpaste`, no need for a sanity check.

## What you need

An email address — preferably one the user actually reads. OpenAlex may contact this address if:

- They detect an unusual request pattern from the user's mailto and want to confirm it's intentional
- A major API change is coming and they want to give heads-up
- (Rarely) An issue with the user's specific usage needs discussion

Use a real email, not a placeholder. `user@example.com` will not get the polite-pool treatment if OpenAlex's anti-abuse heuristics flag it.

## Where to get it

Not applicable — the user types in their own email. Just ask them.

> *"What email should I use for OpenAlex's polite pool? It should be one you actually read, since they may reach out if there's an issue with your usage."*

## Validation

Standard RFC 5322 email regex (a permissive one):

`^[^\s@]+@[^\s@]+\.[^\s@]+$`

This catches obvious typos (`foo@bar`, no TLD; `@bar.com`, no local part) without rejecting weird-but-valid addresses (sub-addresses with `+`, internationalized domains, etc.).

If the regex fails: ask the user to confirm.

## Sanity check

Not really necessary — OpenAlex doesn't reject anonymous calls, so there's no authentication test to run. But you can confirm the polite pool is honoring the mailto by checking the response headers:

```bash
curl -sSI "https://api.openalex.org/works?per-page=1&mailto=<email>" | grep -i "X-Polite-Pool"
```

If the response includes `X-Polite-Pool: true`, you're in. (As of late 2025 this header is not yet standardized; absence doesn't mean rejection. The mailto routing is mostly invisible to clients beyond the rate limit difference.)

## Target env vars + file

Target: **`claude_desktop_config.json` → `mcpServers.rka.env`** (the rka MCP server passes mailto on every OpenAlex call when set).

If the orchestrator daemon is installed, **also** persist to **`orchestrator/.env`**.

If any other MCP server is OpenAlex-aware (e.g., a future literature-search server), set it in that server's env block too. Setting `OPENALEX_MAILTO` broadly is harmless — it's not a secret.

```json
{
  "mcpServers": {
    "rka": {
      "command": "/Users/<you>/.local/bin/rka",
      "args": ["mcp"],
      "env": {
        "OPENALEX_MAILTO": "you@institution.edu"
      }
    }
  }
}
```

## Restart instruction

```
✓ OPENALEX_MAILTO persisted.

Claude Desktop: fully quit (Cmd+Q) and reopen.
RKA orchestrator: docker compose -f docker-compose.yml \
                                 -f orchestrator/docker-compose.yml \
                                 up -d --force-recreate

There's no live-API test for this one — the only observable
effect is a higher rate limit, which you'd only notice if you
were doing batch queries. If OpenAlex queries through Claude
suddenly start failing with 429 errors, the mailto wasn't
picked up; check the env block via `docker compose config`.
```

## Common pitfalls

- **Wrong email field** — OpenAlex used to accept the mailto via a `User-Agent` header (e.g., `User-Agent: my-app/1.0 (mailto:user@example.com)`). The current preferred path is the `mailto` query param OR header `User-Agent: my-app (mailto:user@example.com)`. Either works; the rka MCP server's OpenAlex client handles both.
- **University domain that bounces** — if the user's institutional email bounces (left the institution, address retired), OpenAlex may eventually de-prioritize. Use a personal email that will outlive the user's affiliation for long-running projects.
- **GDPR / privacy concerns** — OpenAlex publishes their rate-limit logs by mailto for transparency. The user's email may appear in public OpenAlex traffic logs. If that's a concern, use a research-aliased email rather than a primary personal one.
- **Free tier confusion** — OpenAlex doesn't have paid tiers. The polite pool is just the rate-limit-uplift; nothing else. Don't confuse with services where mailto unlocks paid features.
