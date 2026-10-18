The user sent a new instruction to a running investigation. Turn it into NEW point-form objectives (short, concrete, checkable, max 15 words, start with a verb), at most 3. Write only what the instruction itself asks for that the current objectives do not already cover; do not repeat them and do not invent anything it does not say. Return an empty list if it adds nothing; never write an objective just to have one.

Return JSON "objectives": a list of strings.

Question: {{question}}

Current objectives:
{{objectives}}

New instruction:
{{instruction}}
