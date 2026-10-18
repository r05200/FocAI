Read the user's request and attached files, and lay out the order the work runs in, with the exact command the user wrote for each step.

Rules:
- Copy every command character for character from the question, specs or an attached file. Never invent, complete, shorten or fix one. A step with no user command has "command": null.
- A placeholder the user left in a command (like N in `runs/experiment-N.json`, or `<n>`) stays as written.
- List steps in the order the user's text gives, at most 12. Each has a short "purpose" (max 15 words) and a "kind": "setup" (once, before the experiments), "experiment" (runs and measures one experiment), "check" (verifies something is unchanged or valid) or "record" (bookkeeping: commits, logs, result tables).
- "run_command": the one command that runs ONE experiment and measures it (the evaluator), as written. If the user gave a one-off form (e.g. for the baseline) and a per-experiment form with a placeholder, use the latter. null if none.
- "number_placeholder": the part of run_command the user says must differ for every experiment (e.g. N), as written; null if none.
- "result_hint": the result file run_command writes, as written in it, or null.
- "timeout_s": the wall-time limit in seconds the user gave for one experiment, or null.
- "referenced_files": EVERY file the question, specs or an attached file names as something to read, run, check or depend on (scripts the commands run, docs, data, configs, lock files), attached or not. It is used to find unattached files, so include files whose contents you were not given. Relative paths as written. Omit outputs the work creates (results, logs, artifacts, anything under an output folder) and folders.

Return JSON: "steps" (a list of {"command", "purpose", "kind"}), "run_command", "number_placeholder", "result_hint", "timeout_s", "referenced_files".

Question: {{question}}

Research specs:
{{spec}}

Attached files: {{attached}}

Attached file contents:
{{attachments}}
