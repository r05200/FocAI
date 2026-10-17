File this {{kind}} into a research vault. Return JSON:
- "title": specific, max 10 words (reuse the text's own title)
- "summary": 1-2 concrete sentences, max 40 words
- "tags": 2-5 lowercase hyphenated topic tags; reuse an existing tag only if it truly matches
- "investigate": true only if the text asks to look into something or suggests it might help; false for findings and facts

Existing tags: {{existing_tags}}

Text:
"""
{{text}}
"""
