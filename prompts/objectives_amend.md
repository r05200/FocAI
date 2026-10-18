The user sent a new instruction to a running investigation. Turn it into NEW point-form objectives (short, concrete, checkable, max 15 words, starting with a verb), at most 2. Write only what the instruction asks that the current objectives don't cover; don't repeat them or invent anything. Return an empty list if it adds nothing.

Return JSON "objectives": a list of strings.

Question: {{question}}

Current objectives:
{{objectives}}

New instruction:
{{instruction}}
