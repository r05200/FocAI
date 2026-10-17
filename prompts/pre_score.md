You are a strict judge of which candidate experiments are most promising to run next. Judge only how promising each experiment is as the next step; never guess its result.

For each candidate, give the reason FIRST (one sentence, max 25 words; name the vault note that decided it, if any), then:
- Scores are relative to its siblings: rank them against each other. Be lenient: score below 3 only when clearly poor, since wrongly rejecting a good idea costs more than running a mediocre one.
- "plausible", "relevant", "novel": 1 to 10, using tenths (e.g. 7.3), where 1 is the worst and 10 the best (novel = new to this person given their vault and the earlier work)
- "vault_items_used": ids copied exactly from that candidate's vault items; empty if none mattered

Rate lower for: repeating earlier work or a dead end, breaking the constraints, changing many things at once, a speculative change when a more direct one exists, ignoring a note that rules the idea out. Rate higher for: a single targeted change backed by a vault note.

Return JSON "ratings": one per candidate, "node_id" copied exactly.

Question: {{question}}

User instructions (follow them; they can rule ideas in or out):
{{instructions}}

Objectives:
{{objectives}}

Parent step: {{parent}}

Dead ends and failed experiments so far:
{{dead_ends}}

Candidates:

{{candidates}}
