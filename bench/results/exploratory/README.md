# Exploratory runs, kept but not validated

(Attack reports against Mem0 and MemoryOS used to sit here too. The
paper cites those, so they moved to `../external/`, where a manifest
and a table checker bind them. What follows is about the two LLM-suite
runs that remain, and nothing in the paper rests on either.)

Two LLM-suite runs from darwin-memo 0.4.0, retained because they record
what was tried, not because anything rests on them. No claim in the
paper cites either file; the LLM-mode results the paper does use are
`llm-llama.json` and `llm-qwen.json` in the parent directory.

They sit outside the manifest-validated tree because they cannot satisfy
the current contract and should not be made to. The `llm` suite now
requires flake accounting (`flakes_marked`, `flakes_fired`,
`fired_false_bad`, `fired_false_good`, `reported_cum_delta`) that did not
exist when these were produced. Back-filling those fields would mean
inventing measurements, and relaxing the suite's required-metric set to
admit them would weaken the check for every current file to accommodate
two that nothing depends on.

The alternative considered and rejected was excluding them by name from
the CI glob. This repository has already been burned once by a
hardcoded validation list that quietly skipped the only two files unable
to pass; a directory boundary that a reader can see beats an exception
list that they cannot.
