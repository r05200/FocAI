The user changed their question or instructions mid-run. Re-judge branches that were parked or are still waiting to run, using the instructions below; they override anything earlier.

Judge each branch by its topic: does it fit what the user asks for NOW? A branch parked for a reason the new instructions no longer care about should now rate well (for example: parked for taking more steps, but the user now wants it faster regardless of steps). Be lenient: if a branch is reasonably close to what is now asked, score it 5 or higher. Score below 3 only when it is clearly off-topic or ruled out by the new instructions. Rank the branches against each other, so the most useful rate highest. Never guess a branch's result.

For each branch give the reason FIRST (one sentence, max 25 words; say what changed or what still rules it out), then "plausible", "relevant", "novel" (each 1 to 10, using tenths, e.g. 7.3), and "vault_items_used" (ids copied exactly from that branch's vault items; empty if none mattered).

Return JSON "ratings": one per branch, "node_id" copied exactly.

Question: {{question}}

User instructions (latest and strongest):
{{instructions}}

Objectives:
{{objectives}}

Branches:

{{candidates}}
