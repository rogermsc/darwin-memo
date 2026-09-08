"""Docs must agree with the code on the things a reader looks up.

`tests/test_docs_links.py` checks that every name in ``__all__`` appears
*somewhere* in api.md as a word. That is a real guard and it is why the
drift accumulated exactly where it does not look: at fields, subcommands,
event kinds and counts, none of which are `__all__` names.

Found by these assertions on first run: `import`, `pin` and `unpin` were
documented nowhere; api.md listed 11 of MemoryEntry's 16 fields and 7 of
SurvivalConfig's 11; store-format.md documented 7 of the 13 event kinds
the code emits; and three separate places said "six degeneracies" where
the code defines seven.
"""

from __future__ import annotations

import re
from dataclasses import fields as dataclass_fields
from pathlib import Path

import pytest

from darwin_memo import MemoryEntry, SurvivalConfig

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
API = DOCS / "api.md"
STORE_FORMAT = DOCS / "store-format.md"
PACKAGE = ROOT / "darwin_memo"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------- subcommands


def registered_cli_commands() -> set[str]:
    """Every subcommand name any module attaches to the ROOT parser.

    The negative lookbehind matters: `lsub.add_parser` contains
    `sub.add_parser`, so without it this swallowed every ledger sub-op and
    demanded a `darwin-memo decide` line that should not exist.
    """
    found: set[str] = set()
    for source in PACKAGE.glob("*.py"):
        body = _text(source)
        found |= set(
            re.findall(r'(?<![a-z])sub\.add_parser\(\s*\n?\s*"([a-z-]+)"', body)
        )
    return found


def registered_ledger_ops() -> set[str]:
    body = _text(PACKAGE / "cli.py")
    return set(re.findall(r'lsub\.add_parser\(\s*\n?\s*"([a-z-]+)"', body))


def test_api_documents_every_cli_subcommand() -> None:
    documented = _text(API)
    missing = sorted(
        name
        for name in registered_cli_commands()
        if f"darwin-memo {name}" not in documented
    )
    assert not missing, (
        f"api.md documents no `darwin-memo <cmd>` line for: {missing}. "
        "It is the CLI reference; a command absent from it is undiscoverable."
    )


def test_api_documents_every_ledger_operation() -> None:
    documented = _text(API)
    ops = registered_ledger_ops()
    assert ops, "the ledger-op parser found nothing -- it is broken, not the CLI"
    missing = sorted(
        op
        for op in ops
        if not re.search(rf"ledger\b[^\n]*\b{re.escape(op)}\b", documented)
    )
    assert not missing, f"api.md's ledger operations omit: {missing}"


# ------------------------------------------------------------------- fields


@pytest.mark.parametrize(
    "cls, doc",
    [(MemoryEntry, API), (SurvivalConfig, API), (MemoryEntry, STORE_FORMAT)],
    ids=["MemoryEntry in api.md", "SurvivalConfig in api.md", "MemoryEntry on disk"],
)
def test_documented_dataclass_fields_are_complete(cls: type, doc: Path) -> None:
    """Every field of a persisted or configured dataclass is named in the doc.

    The five trust-lifecycle fields (pinned, probation, juvenile,
    imported_from, imported_at) were missing from both, and they are
    precisely the fields docs/threat-model.md depends on.
    """
    body = _text(doc)
    names = [field.name for field in dataclass_fields(cls)]
    missing = [name for name in names if not re.search(rf"\b{name}\b", body)]
    assert not missing, f"{doc.name} never names {cls.__name__} fields: {missing}"


# -------------------------------------------------------------- event kinds


def emitted_event_kinds() -> set[str]:
    """Every kind passed to Ledger._log."""
    body = _text(PACKAGE / "ledger.py")
    return set(re.findall(r'self\._log\(\s*\n?\s*"([a-z_]+)"', body))


def test_store_format_documents_every_event_kind() -> None:
    kinds = emitted_event_kinds()
    assert len(kinds) > 5, f"the event-kind parser found only {kinds} -- it is broken"
    body = _text(STORE_FORMAT)
    missing = sorted(kind for kind in kinds if f"`{kind}`" not in body)
    assert not missing, (
        f"store-format.md documents no event kind for: {missing}. "
        "The event log is the audit trail; an undocumented kind cannot be read."
    )


# ------------------------------------------------------------ finding codes


def defined_finding_codes() -> set[str]:
    found: set[str] = set()
    for source in (PACKAGE / "observe.py", PACKAGE / "diagnose.py"):
        found |= set(re.findall(r'code="([a-z_]+)"', _text(source)))
    return found


def test_docs_do_not_miscount_the_degeneracies() -> None:
    """Three docs said "six degeneracies" while the code defined seven.

    A stated count is a claim that rots the moment a rule is added, so the
    English word is checked against the constants rather than trusted.
    """
    codes = defined_finding_codes()
    assert codes, "the finding-code parser found nothing -- it is broken"
    words = {
        3: "three",
        4: "four",
        5: "five",
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
        10: "ten",
    }
    correct = words[len(codes)]
    wrong = [w for n, w in words.items() if w != correct]
    offenders: list[str] = []
    for doc in [*sorted(DOCS.rglob("*.md")), ROOT / "README.md"]:
        if "research" in doc.parts or "superpowers" in doc.parts:
            continue  # dated working notes, true when written
        body = _text(doc)
        for word in wrong:
            if re.search(rf"\b{word}\s+degenerac", body):
                # Path from the repo root, not doc.name: README.md and
                # docs/README.md share a basename, and reporting the bare
                # name sent me to the wrong file.
                offenders.append(f"{doc.relative_to(ROOT)}: says '{word} degeneracies'")
    assert not offenders, (
        f"the code defines {len(codes)} finding codes ({correct}): "
        + "; ".join(offenders)
    )


def test_every_finding_code_is_documented() -> None:
    body = _text(API)
    missing = sorted(code for code in defined_finding_codes() if code not in body)
    assert not missing, (
        f"api.md does not document these doctor findings: {missing}. "
        "The code is what a user searches for when one fires."
    )


# --------------------------------------------------------------- signatures


def test_documented_signatures_match_the_code() -> None:
    """A signature in the docs is a promise about how to call something.

    api.md gave `charge_upkeep(protect=())`, which had gained a `scale`
    parameter; a reader copying it would not know the knob existed.
    """
    import inspect

    from darwin_memo.store import MemoryStore

    body = _text(API)
    checks = {
        "charge_upkeep": MemoryStore.charge_upkeep,
        "ticks_to_starvation": MemoryStore.ticks_to_starvation,
    }
    missing_params: list[str] = []
    for name, function in checks.items():
        if f"`{name}`" not in body:
            missing_params.append(f"{name} is not documented at all")
            continue
        for parameter in inspect.signature(function).parameters:
            if parameter == "self":
                continue
            # The parameter must appear somewhere in the 400 characters
            # following the signature -- the table row or the prose under it.
            where = body.index(f"`{name}`")
            if parameter not in body[where : where + 400]:
                missing_params.append(f"{name}() omits `{parameter}`")
    assert not missing_params, "; ".join(missing_params)
