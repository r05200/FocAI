Judge what an executed experiment showed, not how promising the idea sounded. Do not propose next steps.

Return JSON, reason FIRST:
- "reason": one sentence, max 30 words: what the result shows vs the baseline, your confidence, and the vault note that mattered, if any
- "post_score": 1 to 10 (tenths, e.g. 6.4) for how far the result advances the research. Measured numbers beat narrative: a change within noise is no improvement; an informative failure scores above zero; score lower for confounds.
- "criteria_progress": objective ids the result advances, copied exactly; empty if none
- "vault_items_used": ids copied exactly from the vault items below; empty if none

Question: {{question}}

User instructions (they can change what counts as progress):
{{instructions}}

Objectives:
{{objectives}}

Baseline and best result so far:
{{baseline}}

Experiment ({{node_type}}): {{description}}

Result:
{{result}}

Vault items ({{people}}) close to this experiment:
{{vault_items}}

Dead ends and failed experiments so far:
{{dead_ends}}
