---
description: "Search the RKA knowledge base. Pass 2-4 keyword terms (longer queries return empty). Searches journal entries, decisions, literature, missions, claims, and clusters by default."
argument-hint: "<2-4 keyword terms>"
---

Use the user's query (the text after the slash command) as the search query. If the user provided no query, ask them for 2-4 keyword terms before searching.

Call `rka_search(query="<user query>", limit=10)` to retrieve matching entities across the knowledge base.

Present the results as a numbered list:
1. **[entity_type] entity_id** — one-line summary or first 80 chars of content
2. ...

If `rka_search` returns empty, suggest the user try shorter (2-3 word) or different keywords; long natural-language queries often return no matches.

Do not call additional tools to expand on individual results unless the user asks. Keep the response under 20 lines.
