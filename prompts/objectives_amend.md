The user sent a new instruction to a running investigation. Turn it into 1 to 3 NEW point-form objectives (short, concrete, checkable, max 15 words, start with a verb). Write only what it adds; do not repeat the current objectives. Return an empty list if it adds nothing.

Return JSON "objectives": a list of strings.

Question: {{question}}

Current objectives:
{{objectives}}

New instruction:
{{instruction}}
