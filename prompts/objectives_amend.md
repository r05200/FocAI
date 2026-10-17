The user sent a new instruction to a running investigation. Turn it into 1 to 3 NEW objectives, in point form: one short, concrete, checkable statement each (max 15 words; start with a verb). Write only what the instruction adds. Do not repeat or rephrase the current objectives. If the instruction adds nothing new, return an empty list.

Return JSON "objectives": a list of strings.

Question: {{question}}

Current objectives:
{{objectives}}

New instruction:
{{instruction}}
