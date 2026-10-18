Turn this request into point-form objectives that say what the user asked for and nothing more. Use only the question and the research specs. Write one objective per distinct thing they asked for: at least 1, at most 5, and never pad the list to reach a number. Each is short, concrete and checkable (max 15 words, start with a verb like Find, Show, Compare), keeps the user's own constraints and priorities, don't overlap.

Do not invent. No goals, methods, metrics, comparisons, baselines or background the request does not mention, and no "best practice" extras. A narrow request gives a short list. Standing directives, if present, are constraints on how to work: do not turn them into objectives unless the request itself asks for that.

Also report the command the user gave for running one experiment, if they gave one: copy it character for character from the question, the specs or the attached files, without adding or changing anything. If they did not write one, use null. Do not make one up.

Return JSON: "objectives" (a list of strings), "run_command" (string or null), "result_hint" (the file the user said results are written to, or null).

Question: {{question}}

Research specs:
{{spec}}

Attached files:
{{attachments}}
