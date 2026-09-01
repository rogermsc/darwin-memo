# Attacks on curators we did not write

These are the paper's answer to the standing objection that every other
result in it runs on an environment we built, which makes them the
load-bearing evidence rather than the incidental kind. They lived in
`../exploratory/` until the paper grew whole sections around them
(`\S`sec:mem0, `\S`sec:memoryos), at which point that directory's stated
rationale --- "No claim in the paper cites either file" --- had quietly
stopped being true of them. It is true again of the two files still there.

They are not validated by `python -m bench.report --check
--require-manifest`, and should not be. That validator reads
`payload["runs"]` and enforces a suite's required metric set; these files
have no runs and no suite, because they are attack reports against somebody
else's system. Relaxing the validator to admit them would weaken the check
for the 36 files that can satisfy it, to accommodate five that cannot.

They are bound instead by two things that run on every PR:

- `MANIFEST.json` here: the producing command, the `source_commit`, the
  date, the curator model, and the version of the attacked package.
- `tests/test_paper_tables_match_evidence.py`: every cell of
  `tab:mem0` and `tab:memoryos` is re-derived from these files, the
  caption's `$0$ of $9$` included, and the manifest is asserted to name
  exactly the files present. Edit one digit in the paper and one test fails.

`target_version` is `null` in every current entry. These runs predate
`bench.external.external_versions`, which records the attacked package's
version into every report from now on; back-filling it would mean inventing
a measurement, so the manifest says it was not captured and pins the runs by
`source_commit` and date instead.
