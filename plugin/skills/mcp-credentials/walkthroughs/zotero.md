# Zotero — `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, `ZOTERO_LIBRARY_TYPE`

The `zotero-mcp` server lets Claude search the user's Zotero library, retrieve full-text PDFs they've captured via the Zotero Connector, and link bibliographic metadata into RKA. Three env vars are required.

## What you need

| Field | Format | Notes |
|---|---|---|
| `ZOTERO_API_KEY` | 24-char alphanumeric | Per-user, scope-restrictable |
| `ZOTERO_LIBRARY_ID` | Numeric (user) or group ID | User ID = a number on the user's account page; group ID = the number in the group's URL |
| `ZOTERO_LIBRARY_TYPE` | `user` or `group` | Tells zotero-mcp which Zotero API base path to use |

Most users want their personal library → `user`.

## Where to get it

### Step A — Generate the API key

1. Visit https://www.zotero.org/settings/keys (the user needs to be logged in)
2. Click **"Create new private key"**
3. Set:
   - **Description**: `Claude Desktop` (or anything memorable)
   - **Personal Library** section: check **"Allow library access"**. Decide read-only vs read/write based on what you'll do — read-only is safer if Claude will only fetch references; read/write enables RKA's literature-linking flow to update Zotero items.
   - **Default group permissions**: `Read Only` is fine unless the user works in a shared group library and wants Claude to modify it.
4. Click **Save Key**. Zotero shows the key once — copy it immediately. It will look like 24 chars of `A-Za-z0-9` (e.g., `Pgxxxxxxxxxxxxxxxxxxxxxx`).

### Step B — Find the Library ID

**For personal library** (most common):

1. Visit https://www.zotero.org/settings/keys
2. At the top of the page, the section "Your userID for use in API calls" shows a number (e.g., `9646912`). That's the `ZOTERO_LIBRARY_ID`.

**For group library**:

1. Visit https://www.zotero.org/groups
2. Click into the relevant group
3. The URL ends with `/groups/<number>/<groupname>`. The `<number>` is the `ZOTERO_LIBRARY_ID`.

### Step C — Pick the type

- Personal library → `user`
- Group library → `group`

If the user wants both (search across both), you can't do it in one MCP server entry — they'd need two server entries with different names (`zotero-personal`, `zotero-group-X`). Default to whichever they care about most.

## Validation

| Field | Regex |
|---|---|
| `ZOTERO_API_KEY` | `^[A-Za-z0-9]{24}$` |
| `ZOTERO_LIBRARY_ID` | `^\d+$` |
| `ZOTERO_LIBRARY_TYPE` | `^(user\|group)$` |

If the key fails:
- Length off by 1 or 2 → likely paste truncation. Have them re-copy.
- Contains special chars → they pasted the key with surrounding markup or whitespace. Strip and retry.

## Sanity check (recommended)

Hit the Zotero API with the user's credentials to confirm both the key and library ID are valid:

```bash
KEY="$( pbpaste )"
ID=9646912           # the library id they just provided
TYPE=user            # or group

# List 1 item from the library
curl -sS -H "Zotero-API-Key: $KEY" \
  "https://api.zotero.org/${TYPE}s/${ID}/items?limit=1&format=json" \
  | head -c 300

unset KEY
```

Expected: JSON array (possibly empty if the user's library has no items). 403 or 404 means the key doesn't have permission for that library — usually wrong library ID or wrong type.

## Target env vars + file

Target: **`claude_desktop_config.json` → `mcpServers.zotero.env`**

After persistence:

```json
{
  "mcpServers": {
    "zotero": {
      "command": "<existing command — DO NOT change>",
      "args": ["<existing args — DO NOT change>"],
      "env": {
        "ZOTERO_API_KEY": "Pgxxxxxxxxxxxxxxxxxxxxxx",
        "ZOTERO_LIBRARY_ID": "9646912",
        "ZOTERO_LIBRARY_TYPE": "user"
      }
    }
  }
}
```

If `mcpServers.zotero` doesn't exist yet, the user hasn't installed the `zotero-mcp` server — surface that. The credentials alone don't give Claude Desktop the tools; they need the server entry too. Point them at https://github.com/54yyyu/zotero-mcp for install instructions, then re-run this walkthrough.

The orchestrator daemon **also** uses these env vars (for the `rka_link_literature_to_zotero` flow). If RKA is installed, additionally persist to **`orchestrator/.env`**.

## Restart instruction

```
✓ Zotero credentials persisted.

To activate in Claude Desktop:
  Fully quit (Cmd+Q) and reopen.

To activate in the RKA orchestrator daemon:
  docker compose -f docker-compose.yml \
                 -f orchestrator/docker-compose.yml \
                 up -d --force-recreate rka-orchestrator

Verify by asking me to "list recent items in my Zotero library"
(Claude Desktop will call zotero_get_recent), or by checking the
orchestrator's `/health` endpoint then trying a literature
linkage.
```

## Common pitfalls

- **User ID vs username** — `ZOTERO_LIBRARY_ID` is a number, not the user's screen name. The username (`carolus_linnaeus`) won't work.
- **Type mismatch** — using `type=user` with a group ID, or vice versa, returns 404 from the Zotero API. The error doesn't say "wrong type" — it says "not found".
- **Read-only key + RKA write flow** — `rka_link_literature_to_zotero` may want to write back tags or attached files to Zotero. If the user wants that, the key needs read+write permission. Re-mint if necessary.
- **Library with many items + first call** — zotero-mcp may cache locally on first call; the user might see a delay. Normal.
