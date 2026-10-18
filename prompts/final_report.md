Write the final report of a research run for the person who asked. Be concrete and honest: what was measured, supported, refuted or inconclusive, and what is still open; claim no more than the findings show. Combine ALL the branches into one report: where they agree, where they conflict, which were parked or not run.

Explain HOW the run reached its answer and WHY each step that led there was taken. Justify each step by its reasoning, never by its scores: what the earlier result showed, the hypothesis's rationale, why the previous step chose this as its next action ("Chosen because"), and why it was kept or parked. Build this from the branch blocks below (the other agents' own justifications); do not invent reasons they did not give. Mark a likely cause as unverified.

Return JSON:
- "title": a headline of at most 12 words
- "answer": the report, a few short paragraphs. Name the change that was kept, if any, and its measured effect against the baseline; in a research run without files, name the best resources found and what they show. Include a short paragraph on how the run got there: the chain of steps and the reasoning that linked each to the next.
- "steps": one entry per step on the way to the answer (root first, plus any parked branch that changed the direction), each {"node_id", "why"}. "why" is one or two sentences: why this step was tried and what it led to, from the justifications given.

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

What the run kept (the change left applied to the files, or a research run's best direction): {{kept}}
