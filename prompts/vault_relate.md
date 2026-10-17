A new item was added to a research knowledge vault. Below it are its nearest existing items by
embedding similarity. For each neighbor, decide how the NEW item relates to it.

Relations (pick exactly one per neighbor):
- "contradicts": the two make conflicting claims, or one undermines the other's conclusion.
- "supports": one provides evidence, results or reasoning that backs the other's claim.
- "agrees": both state the same view or conclusion, without one being evidence for the other.
- "unrelated": similar wording or topic, but neither has any bearing on the other's claims.

Questions and notes count too: a note that doubts a paper's claim contradicts it; a paper that
answers a question supports it. Prefer "unrelated" over guessing.

Return JSON with "relations": one entry per neighbor, in the same order, each with
"neighbor_id" (copied exactly), "relation", and "reason" (one short sentence, at most 25 words,
naming the specific point of contact).

NEW item ({{new_kind}}, from {{new_person}}):
Title: {{new_title}}
Summary: {{new_summary}}

Neighbors:
{{neighbors}}
