Turn this request into 3 to 5 point-form objectives: short, concrete, checkable (max 15 words, start with a verb like Find, Show, Compare). Keep the user's constraints and priorities; invent nothing; no overlap.

Also report the command the user gave for running one experiment, if they gave one: copy it character for character from the question, the specs or the attached files, without adding or changing anything. If they did not write one, use null. Do not make one up.

Return JSON: "objectives" (a list of strings), "run_command" (string or null), "result_hint" (the file the user said results are written to, or null).

Question: {{question}}

Research specs:
{{spec}}

Attached files:
{{attachments}}
