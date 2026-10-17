The user changed their question or instructions mid-run. Re-judge parked and still-waiting branches against the instructions below, which override anything earlier.

Judge each by topic: does it fit what is asked NOW? A branch parked for a reason the new instructions no longer care about should rate well (e.g. parked for taking more steps, but the user now wants it faster regardless). Be lenient: reasonably close scores 5 or higher; below 3 only if clearly off-topic or ruled out. Rank branches against each other. Never guess a branch's result.

Per branch: "reason" FIRST (one sentence, max 25 words: what changed or still rules it out), then "plausible", "relevant", "novel" (1 to 10, tenths), and "vault_items_used" (ids copied exactly from that branch's vault items; empty if none).

Return JSON "ratings": one per branch, "node_id" copied exactly.

Question: {{question}}

User instructions (latest and strongest):
{{instructions}}

Objectives:
{{objectives}}

Branches:

{{candidates}}
