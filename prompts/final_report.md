Write the final report of a research run for the person who asked. Be concrete and honest: what was measured, supported, refuted or inconclusive, and what is still open; claim no more than the findings show. Combine ALL branches into one report: where they agree, where they conflict, which were parked or not run.

Explain HOW the run reached its answer and WHY each step was taken. Justify each step by its reasoning, never its scores: what the earlier result showed, the hypothesis's rationale, why the previous step chose this as its next action ("Chosen because"), and why it was kept or parked. Build this from the branch blocks below (the agents' own justifications); invent no reasons. Mark a likely cause as unverified.

Use the run vault below: it holds what each branch learned (ideas and whole-branch findings). Pull in everything that helps answer the question, including negative results (what was refuted, came up empty or was parked, and so what is ruled out). Skip only what is off-topic or repeated.

Return JSON:
- "title": a headline of at most 12 words
- "answer": the report, a few short paragraphs. Name the change kept, if any, and its measured effect against the baseline; in a run without files, name the best resources found and what they show. Include a short paragraph on how the run got there: the chain of steps and the reasoning linking each to the next. End with a line "## Suggested next steps" and 2 to 4 bullet points ("- ") of concrete follow-ups: open questions, branches worth restoring or deepening, checks that would firm up unverified parts.
- "steps": one entry per step on the way to the answer (root first, plus any parked branch that changed direction), each {"node_id", "why"}. "why" is one or two sentences: why the step was tried and what it led to, from the justifications given.
- "sources": ids of every node whose result (from the branch blocks, findings log or run vault's node ids) the answer draws on, positive or negative; copy exactly, no root, no conclusion.

Question: {{question}}

User instructions:
{{instructions}}

Objectives:
{{objectives}}

Baseline result: {{baseline}}

Every branch (path from the root, family, verdict, why it was chosen, its rationale, what it found, the likely cause, why it was kept or parked):
{{branches}}

Findings log (oldest first):
{{findings}}

Run vault (what this run learned, one entry per idea; node ids in brackets):
{{run_vault}}

What the run kept (the change left applied to the files, or a research run's best direction): {{kept}}
