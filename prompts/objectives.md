Turn this request into point-form objectives that say what the user asked for and nothing more. Use only the question and research specs. One objective per distinct thing asked: at least 1, at most 8. Lean toward more objectives: split a compound request into its separate parts and give each its own point, rather than merging them, but never pad. Each is short, concrete and checkable (max 15 words, starting with a verb like Find, Show, Compare), keeps the user's constraints and priorities, and doesn't overlap.

Do not invent: no goals, methods, metrics, comparisons, baselines, background or "best practice" extras the request doesn't mention. A narrow request still gives a short list. Standing directives are constraints on how to work: don't make them objectives unless the request asks.

Also report the command the user gave for running one experiment, if any: copy it character for character from the question, specs or attached files, adding or changing nothing. If none, use null. Never make one up.

Return JSON: "objectives" (a list of strings), "run_command" (string or null), "result_hint" (the file the user said results are written to, or null).

Question: {{question}}

Research specs:
{{spec}}

Attached files:
{{attachments}}
