Read the user's request and the files they attached, and lay out the order the work runs in, with the exact command the user wrote for each step.

Rules:
- Copy every command character for character from the question, the specs or an attached file. Never invent, complete, shorten or fix a command. A step the user gave no command for has "command": null.
- A placeholder the user left in a command (like N in `runs/experiment-N.json`, or `<n>`) stays exactly as written.
- List the steps in the order the user's text says to do them, at most 12. Each has a short "purpose" (max 15 words) and a "kind": "setup" (done once before the experiments), "experiment" (runs one experiment and measures it), "check" (verifies something is unchanged or valid) or "record" (bookkeeping: commits, logs, result tables).
- "run_command": the one command that runs ONE experiment and measures it (the evaluator), copied as written. If the user wrote both a one-off form (e.g. for the baseline) and a per-experiment form with a placeholder, use the per-experiment form. null if they wrote none.
- "number_placeholder": the exact part of run_command the user says must be different for every experiment (an experiment number such as N), as written; null if there is none.
- "result_hint": the result file run_command writes, as written in it, or null.
- "timeout_s": the wall-time limit in seconds the user gave for one experiment, or null.
- "referenced_files": EVERY file the question, the specs or an attached file names as something to read, run, check or depend on as an input (scripts the commands run, docs, data, configs, lock files), whether or not it is attached. This list is used to find the files that were not attached, so do not leave a file out because you were not given its contents. Give relative paths exactly as written. Leave out outputs the work creates (results, logs, artifacts, anything under an output folder) and folders.

Return JSON: "steps" (a list of {"command", "purpose", "kind"}), "run_command", "number_placeholder", "result_hint", "timeout_s", "referenced_files".

Question: {{question}}

Research specs:
{{spec}}

Attached files: {{attached}}

Attached file contents:
{{attachments}}
