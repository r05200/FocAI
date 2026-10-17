The user just steered this research run: {{change}}

Rate how relevant each node below is to what the user wants NOW. Nodes may be waiting to run, parked, or already finished. Do not re-judge results; judge how much each node matters to the current direction. Never guess unseen results.

Be lenient: a node that partly serves the new direction keeps a middle score or better. Score below 4 only if a node clearly no longer matters.

Per node: "reason" FIRST (one sentence, max 25 words, naming what in the instructions it serves or why it no longer does), then "relevant" (1 to 10, tenths, e.g. 7.3), then "metric_needed": if the instruction asks about a quantity this node's experiment did not measure (compare with its measured keys), the name of that quantity as a short key (e.g. "memory_mb"); otherwise "".

Return JSON "ratings": one per node, "node_id" copied exactly.

Question: {{question}}

User instructions (latest and strongest):
{{instructions}}

Objectives:
{{objectives}}

Result keys the baseline measures: {{measured}}

Findings so far:
{{findings}}

Nodes:

{{nodes}}
