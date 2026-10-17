File this {{kind}} into a research vault. Return JSON:
- "title": specific, max 10 words (reuse the text's own title if it has one)
- "summary": 1-2 concrete sentences, max 40 words
- "tags": 2-5 lowercase hyphenated topic tags; reuse an existing tag only if the topic really matches
- "investigate": true only if the text asks to investigate or look into something, or just suggests it might help ("maybe this could help"); false for findings and facts

Existing tags: {{existing_tags}}

Text:
"""
{{text}}
"""
