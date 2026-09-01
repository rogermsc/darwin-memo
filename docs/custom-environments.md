# Writing your own environment

The environment is the whole trick. Everything else in this package is
bookkeeping around one question: *what, in your system, actually pushes back?*

This page is the task the README calls the most load-bearing one and then
covers in fifty lines. It assumes you have run `darwin-memo demo` and want the
loop pointed at your own world.

## The contract

Two methods and an attribute. There is no base class to inherit and nothing to
register: `Environment` is a `typing.Protocol`, so anything with these members
is one.

```python
class Environment(Protocol):
    resource_scale: float
    def tasks(self, cycle: int) -> list[Task]: ...
    def verify(self, task: Task, answer_text: str) -> Outcome: ...
```

**The one rule: `verify` must measure, never grade.** If your `verify` would
end in a model scoring an answer, stop -- this package is the wrong tool, and
the README says which ones are not.

## Step 1: find the conserved resource

A conserved resource is a quantity the world tracks whether or not anyone is
watching, that goes down when you are wrong and up when you are right, and
that nobody in the loop can simply assert.

| Good | Why |
|---|---|
| Tests passing | Counted by the runner, not by you |
| Bytes freed on disk | The filesystem answers |
| Dollars of spend avoided | The invoice answers |
| Rows deduplicated | `COUNT(*)` answers |
| Claims that still reconcile | The released data answers |

| Bad | Why |
|---|---|
| A relevance score | Something graded it |
| "Did the user seem happy" | Nobody measured anything |
| Tokens saved | Usually a proxy, and gameable by answering less |
| Retrieval hit rate | Measures the retriever, not the outcome |

The test to apply: **could a sufficiently motivated liar produce this number
without changing the world?** If yes, it is a proxy.

Two questions decide the rest of your design.

*Is inaction free?* In `StorageEnv` it is: not deleting a file costs nothing,
which is why protective knowledge ("never delete X") eventually starves as
redundant with the default. If holding costs something in your world, price
it -- `RentedStorageEnv` exists to show what changes when you do.

*How asymmetric is a mistake?* `StorageEnv` charges 3x the file size for
deleting a protected file, because that is the real restore cost, not a
penalty invented to punish. Use your real cost. If you cannot name one, the
asymmetry is a judgment and you have smuggled a grader in.

## Step 2: `tasks(cycle)`

Return the decisions your world faces this cycle. `Task.prompt` is what
retrieval matches against, `Task.context` is an opaque dict that only your
`verify` reads -- put the identifiers you will need to measure the outcome in
there.

Make the prompt share vocabulary with your corpus. Retrieval mutes any entry
whose lexical overlap with the task is below `LexicalRetriever(min_coverage=0.25)`,
so a task phrased in words your documents never use retrieves nothing, decides
nothing, and earns nothing.

Draw randomness from `cycle_rng(seed, cycle, stream)` rather than
`random.Random(seed + cycle)`. The obvious version makes adjacent seeds shifted
windows of one another, so "ten seeds" are not ten independent draws.

## Step 3: `verify(task, answer_text)`

You get the memory's answer as text and must return a measured `Outcome`.
Almost always three branches:

```python
def verify(self, task: Task, answer_text: str) -> Outcome:
    act = decision_polarity(
        answer_text,
        extra_positive=("safe to cancel",),
        extra_negative=("do not cancel", "keep paying"),
    )
    if not act:
        return Outcome(delta=0.0, detail="declined")   # silence is conservative
    measured = self._go_and_measure(task.context)      # the world answers
    return Outcome(delta=measured, detail="cancelled")
```

**The action-vocabulary trap.** `decision_polarity`'s built-in markers speak
delete/remove and apply/keep, the bundled environments' dialects. A new verb
("cancel", "migrate", "restart", "cite") reads as *silence* on every answer, so
nothing ever acts, nothing earns, and the whole population starves around cycle
20 with no error raised anywhere. Pass `extra_positive`/`extra_negative`.

**The same trap has a second form, and it is not documented anywhere else.**
If your outcome depends on a *value* the memory produced rather than only on
its yes/no, you now have a second phrase-reading rule with the same failure
mode. `bench/paperclaim_env.py` reads the quoted figure with
`re.compile(r"\breports\s+(-?\d+(?:\.\d+)?)")`, so a corpus that says "the
value is 8" instead of "reports 8" quotes nothing, scores zero everywhere, and
starves exactly like a missing verb. If you write one of these, say so loudly
next to it, and make "acted but produced nothing measurable" return `0.0`
rather than a penalty -- it is silence, not a failure.

**Absence is not a bad outcome.** Whenever your measurement can be *missing*
(a skipped test, a timed-out job, a null column, a 404), that is a third state.
Booking it as a negative is wrong twice over: it punishes an entry that caused
nothing, and it pays credit the day the missing measurement turns into a good
one. `darwin_memo/ci.py` returns `None` for exactly this.

## Step 4: pick `resource_scale`

Set it to *one typical good outcome* in your resource's own units:
`StorageEnv` uses `100_000.0` for bytes; a test-suite environment uses a
handful of tests; `PaperClaimEnv` uses `2.0` for outcomes of ±1 and ±3. A
settled delta equal to `resource_scale` earns about 76% of the maximum credit.
Mechanics, symptoms in both directions, and starting points per profile are in
the [tuning guide](tuning.md#resource_scale-environment-attribute-ledger-argument-survivalconfig-field-default-10-on-the-ledger-and-cli).

## Step 5: unit-test `verify` before you run a loop

This is the step that saves the day. `verify` is a pure function from
(context, text) to a float, so table-drive it and pin every branch:

```python
@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("The paper reports 0 for it. Safe to cite.", 1.0),
        ("The paper reports 8 for it. Safe to cite.", -3.0),
        ("That figure is stale, do not cite it.", 0.0),
        ("Safe to cite.", 0.0),
    ],
)
def test_verify_measures_the_quoted_figure(answer, expected):
    assert env.verify(task, answer).delta == expected
```

If every row returns `0.0`, your action vocabulary is wrong and you have just
caught the starvation cliff in a test that runs in a millisecond instead of in
a thirty-cycle run that looks like a tuning problem.

## When the run still degenerates

The loop's `SurvivalReport.health_warning()` and `darwin-memo doctor` both name
these, but they are cheaper to recognise up front. Every one of them ends the
same way -- the population dying around cycle 20 with every delta at zero.

1. **Action vocabulary.** Nothing acts. See step 3.
2. **Relevance floor.** Nothing retrieves: task phrasing shares no vocabulary
   with the corpus. Use an embedding retriever, or fix the phrasing.
3. **Starvation cliff.** Entries spawn at 1.0 energy and pay 0.05 upkeep, so a
   population that never earns dies at cycle ~20. If everything dies at once
   around there, your environment never paid out -- check 1 and 2 first.
4. **Consolidation eating the population.** If your corpus is templated, entries
   are near-identical and consolidation pools most of them within a few cycles;
   the run then measures the merge rule, not the selection rule. Symptom: a
   large `merges` column early and a population that falls off a cliff at cycle
   3-5 rather than at 20. Raise `merge_threshold` to 0.85-0.95. This is the
   documented cosine-retriever trap arriving through the corpus instead of the
   retriever, and `PaperClaimEnv` needs 0.85 for exactly this reason.
5. **Nothing was ever stale.** If no entry in your corpus is *wrong*, selection
   has nothing to select against and a null result says nothing about the
   mechanism. Seed something false on purpose, and prefer a real value moved to
   the wrong place over an invented one.

## A worked example

`bench/paperclaim_env.py` is a complete environment written against this page,
in about 200 lines: conserved resource, asymmetric cost, both phrase-reading
rules, and its own limits stated in the module docstring.
`tests/test_paperclaim_env.py` is the test shape from step 5 plus the end-to-end
assertion that stale entries die and accurate ones do not.

The three bundled environments are worth reading next, in this order:
`StorageEnv` (`darwin_memo/environments.py`) for the canonical shape,
`TestSuiteEnv` (`darwin_memo/testsuite_env.py`) for a resource counted by a
runner, and `RentedStorageEnv` for what changes when inaction is priced.

## Checklist

- [ ] The resource is counted by something that is not me
- [ ] A liar cannot produce the number without changing the world
- [ ] The cost of a mistake is a real cost, not a chosen penalty
- [ ] Silence returns `0.0` and is the safe reading of an irreversible action
- [ ] A missing measurement is a third state, not a negative one
- [ ] `extra_positive` / `extra_negative` cover my verbs
- [ ] Task prompts share vocabulary with the corpus
- [ ] `verify` is table-driven tested, every branch, before any loop runs
- [ ] `resource_scale` is one typical good outcome
- [ ] Something in the corpus is deliberately wrong
