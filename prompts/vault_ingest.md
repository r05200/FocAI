You are filing an item into a person's research knowledge vault. Read it and describe it so it
can be found and linked later.

Item kind: {{kind}}

Return JSON with:
- "title": a specific title, at most 10 words. If the text has its own title, use it.
- "summary": a short blurb of one or two sentences, at most 40 words, saying what the item
  claims or asks. Be concrete; do not start with "This paper" or "This note".
- "tags": 2 to 5 short lowercase topic tags (use hyphens, not spaces). Reuse tags from the
  existing list below whenever one fits; only invent a new tag when none of them fit.

Existing tags in the vault:
{{existing_tags}}

Item text:
"""
{{text}}
"""
