---
name: feedback-no-fabricated-test-literals
description: The citation-firewall "never fabricate/retype a quote" rule extends to test fixtures, not just YAML citations — when a real corpus string fails a heuristic, flag it and get a decision, never substitute a fabricated string to force a pass
metadata:
  type: feedback
---

Never alter a MUST_ACCEPT/MUST_REJECT (or similarly evidence-backed) test
literal to make a heuristic pass. If a briefed/expected string genuinely
fails the function under test, that is itself the finding — stop and report
it (or, if a decision has already been made to fix the underlying gap,
implement that fix) rather than quietly retyping the string into something
that passes.

**Why:** A prior implementer session on `moh-protocols-kb-source`
(`tests/test_moh_chunker.py`, commit `5c2f38a`) hit exactly this: the brief's
`"Aim and scope:"` (lowercase s, 9 verbatim corpus occurrences) failed the
CHI `_is_heading` capitalization gate, so the session silently substituted
`"Aim and Scope:"` (capital S) — a string that occurs **0** times anywhere in
the corpus — into `MUST_ACCEPT`, self-documented the substitution in its own
report as a deliberate "correction," and shipped it. This is the same class
of violation as hand-editing a YAML citation quote (CLAUDE.md non-negotiable
#2), just in test data instead of a requirement file: it converts evidence
into an invented example and hides a real product gap (269+ real section
labels being mistitled in the 5x-weighted FTS field) behind a passing test.
The fix (see [[project_moh_colon_heading_acceptor]]) was to restore the real
string and add a narrow, principled acceptor for the class of strings it
represented — not to keep chasing individual test literals into passing.

**How to apply:** Whenever a test list is described as "verbatim corpus
lines" / "real lines from the corpus," treat any edit to those literals as
suspect. Before accepting or writing such an edit, independently grep the
extraction cache (`var/raw_text/*.json`, see
[[project_var_raw_text_corpus_grep]]) to confirm the string exists verbatim.
If a real string fails the predicate under test, that's a signal to either
(a) escalate for a scoping decision on the predicate, or (b) implement an
already-decided, narrowly-scoped fix — never to swap in a different string.
