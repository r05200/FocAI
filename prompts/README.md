# Prompts

One file per prompt, loaded by name from the backend. Keep prompts here, not inline in code,
so they can be tuned without touching logic. Planned (added as each step is built):

- `objectives.md` (done): specs -> 3 to 5 point-form objectives; `objectives_amend.md` (done): a new instruction -> new objectives to append
- `propose.md`: propose up to 3 next steps from a node
- `pre_score.md`, `post_score.md`, `rescore.md` (all done): scoring against the objectives and the person's vault; both take the user's instructions
- `vault_ingest.md` (done): title, summary and the investigate flag for a vault item (tags are the person's)
- `profile.md`: known topics, open questions, ruled-out topics
- `synthesize.md`: final answer from kept branches
- `grader.md`: rubric coverage grader (separate from the pruner's judge)
- `agent.md` (done): the single agent turn, used only when the manager has no orchestrator (every normal run goes through the orchestrator's propose/synthesize prompts)
- `amend_rate.md` (done): the amend-objectives agent's loose re-rating of sibling branches
- `propose.md` (done): the hypothesis phase: 2-3 hypotheses from different families, each with a planned experiment and a search/replace edit
- `propose_repair.md` (done): one batched repair of proposals whose edits did not apply
- `synthesize.md` (done): judge one experiment: measured vs explanation, verdict, one-line finding, next action
- `final_report.md` (done): the run's final answer from the findings and the change kept, plus why each step on the way was taken (from the agents' justifications, not scores), logged on the conclusion node
- `steer_rate.md` (done): the steering re-rate after an instruction or a chip toggle: how relevant each node is now (1-10) and a result key it did not measure
- `propose_research.md` (done): the hypothesis phase of a run without files: guesses at what the user wants to see, each with search queries
- `synthesize_research.md` (done): judge a research experiment: are the resources found relevant to the objectives
- `vault_ingest_link.md` (done): a paper link -> title and the abstract (or "No summary found.") parsed from the fetched page
- `fork_brief.md` (done): the brief for the new hypotheses after a confirmed fork (the amended objectives and what was parked)
