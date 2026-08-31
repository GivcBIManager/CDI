"""Optional LLM stage: two-pass, retrieval-backed inference in which the KB is
the validation authority.

Pass A reads the note and reports documentation gaps -- for conditions the note
names as well as conditions it never names (oxygen support without the words
"respiratory failure"). Pass B is shown the clause TEXT retrieved for each
observation and decides which clauses actually govern it.

Two firewalls, in order: an observation whose evidence is not verbatim note text
is discarded (keep_grounded); a clause the model cites that retrieval did not put
in front of it is discarded (keep_candidate_supports), and what survives is then
re-verified verbatim against the store by findings._verified_citations. So this
stage cannot fabricate authority -- and when the documents support nothing, the
finding is reported as "no reference in the KB" rather than dropped or given
borrowed authority.
"""

import ssl
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from cdi_kb import config
from cdi_kb.clauses import Clause, ClauseStore
from cdi_kb.config import ANTHROPIC_MODEL, QUOTE_MATCH_THRESHOLD
from cdi_kb.index import SearchIndex
from cdi_kb.normalize import find_quote
from cdi_kb.requirements_model import DiagnosisRequirement

if TYPE_CHECKING:
    import anthropic

# How many clauses the retrieval pass puts in front of the model per observation.
# The model may only cite from this set, so it bounds both cost and authority.
# Measured against every requirement axis (see test_retrieval_reach_across_every
# _requirement_axis): 29/37 axes can reach their own governing clause at 8,
# 31/37 from 16 onward, and no further gain out to 40 -- so 16 is the point where
# widening stops buying recall and only costs input tokens.
CANDIDATE_LIMIT = 16

# No single source may fill more than this many candidate slots.
#
# De-fusing the journal-typeset CHI guidelines made 1,582 clauses of dense
# guideline prose genuinely searchable for the first time -- previously their
# fused text matched no query term, so they never competed for a slot. A single
# global top-N then let the wordiest source take everything: CHI-CKD filled the
# whole candidate set for "acute kidney injury onset", pushing out the booklet's
# own Renal Failure/Impairment clause, and reach fell 31/37 -> 29/37. Measured at
# caps of 3 / 4 / 6: 26, 28 and 31 of 37 axes respectively.
PER_SOURCE_LIMIT = 6

# Ranked hits fetched before capping. Must be deep enough that a source's own
# best clauses survive the cap even when another source dominates the head.
_OVERFETCH_FACTOR = 25

# Pass B is one API call per observation. Once the LLM was allowed to judge
# conditions the note NAMES (not only ones it never mentions), a real progress
# note went from 3 observations to 10 -- ten sequential round trips, minutes of
# wall clock. They are independent, so they run concurrently.
VALIDATION_CONCURRENCY = 6


@dataclass(frozen=True)
class NoteObservation:
    """One documentation gap the model observed after reading the note.

    `note_quote` must be verbatim note text -- it is the note-side firewall's
    input, and an observation whose evidence is not actually in the note is
    discarded before it can ever reach the KB validation pass.
    """
    condition: str
    axis: str
    issue: str
    note_quote: str


@dataclass(frozen=True)
class KbSupport:
    """A clause the model selected, from the retrieved candidates, as the
    documentation that governs an observation. Verified before it becomes a
    citation -- see findings.compose_inferred_finding."""
    clause_id: str
    quote: str


@dataclass(frozen=True)
class ValidatedObservation:
    """An observation that cleared the note-side firewall, paired with whatever
    KB support survived the candidate-set gate. An empty `supports` is a real
    result, not a failure: it means the documents carry nothing on this point,
    and the finding is reported as "no reference in the KB"."""
    observation: NoteObservation
    supports: list[KbSupport]


def keep_grounded(
    observations: list[NoteObservation],
    note_text: str,
    by_condition: dict[str, DiagnosisRequirement],
) -> list[NoteObservation]:
    """Note-side firewall: an observation survives only if its condition and
    axis exist in the requirement model AND its quote is verbatim note text."""
    kept: list[NoteObservation] = []
    for observation in observations:
        requirement = by_condition.get(observation.condition)
        if requirement is None:
            continue
        if observation.axis not in {rule.axis for rule in requirement.axes}:
            continue
        if not find_quote(observation.note_quote, note_text, QUOTE_MATCH_THRESHOLD).found:
            continue
        kept.append(observation)
    return kept


def retrieve_candidates(
    index: SearchIndex,
    observation: NoteObservation,
    requirement: DiagnosisRequirement,
    limit: int = CANDIDATE_LIMIT,
    per_source: int = PER_SOURCE_LIMIT,
) -> list[str]:
    """The candidate clause set the model is allowed to validate against --
    drawn from the KB by lexical retrieval, never proposed by the model.

    The query is built ONLY from KB-side vocabulary (condition, axis, synonyms).
    The model's own `issue` sentence is deliberately excluded: index._fts_query
    OR-joins every term over 2 characters, so a free-text sentence dilutes the
    query enough to push the governing clause out of the top-N and pull unrelated
    sections in -- making the candidate set, and therefore whether an observation
    is "supported" or "no reference in the KB", depend on the model's phrasing
    rather than on the documents.
    """
    hits = index.search(
        f"{observation.condition} {observation.axis}",
        expansions=list(requirement.synonyms),
        limit=limit * _OVERFETCH_FACTOR,
    )
    kept: list[str] = []
    taken: dict[str, int] = {}
    for hit in hits:
        source = hit.clause_id.split("/")[0]
        if taken.get(source, 0) >= per_source:
            continue
        taken[source] = taken.get(source, 0) + 1
        kept.append(hit.clause_id)
        if len(kept) >= limit:
            break
    return kept


def keep_candidate_supports(supports: list[KbSupport], candidate_ids: list[str]) -> list[KbSupport]:
    """KB-side firewall, first gate: the model may only cite clause_ids that
    retrieval actually put in front of it. A clause_id it invented, or recalled
    from training, is discarded here before quote verification even runs."""
    allowed = set(candidate_ids)
    return [support for support in supports if support.clause_id in allowed]


_CLIENT: "anthropic.Anthropic | None" = None


def _make_client() -> "anthropic.Anthropic":
    """Client with an explicitly built default SSL context.

    This machine's Python carries a pip_system_certs bootstrap that patches ssl
    with pip's vendored truststore; httpx2 then layers the standalone
    truststore package on top, and the double patch recurses infinitely inside
    SSLContext.verify_mode. Passing an explicit context sidesteps httpx2's own
    truststore path. Portable: on unpatched machines this is simply the
    standard default context.

    The anthropic import is function-local so importing this module stays free
    of the SDK: findings.py and the offline test suite reach the firewall
    helpers above without pulling in a network dependency. The client itself is
    a module singleton: it was previously rebuilt (SSL context and all) for every
    API call, so a note with ten observations paid the setup cost eleven times
    and reused no connection.
    """
    global _CLIENT
    if _CLIENT is None:
        import anthropic
        from anthropic import DefaultHttpxClient

        _CLIENT = anthropic.Anthropic(http_client=DefaultHttpxClient(verify=ssl.create_default_context()))
    return _CLIENT


class _ObservationOut(BaseModel):
    condition: str
    axis: str
    issue: str
    note_quote: str


class _Analysis(BaseModel):
    observations: list[_ObservationOut]


class _SupportOut(BaseModel):
    clause_id: str
    quote: str


class _AxisValidation(BaseModel):
    axis: str
    supports: list[_SupportOut]


class _Validation(BaseModel):
    validations: list[_AxisValidation]


_ANALYZE_SYSTEM = (
    "You are a clinical documentation integrity (CDI) specialist reviewing a clinical note. "
    "Read the note and identify documentation gaps.\n"
    "Rules:\n"
    "1. `condition` MUST be copied exactly from the ALLOWED CONDITIONS catalogue.\n"
    "2. `axis` MUST be one of the axes listed for that condition in the catalogue.\n"
    "3. Report an axis as a gap when the condition is clinically evident in this patient "
    "(whether or not the note names it) AND that axis is not documented FOR THAT CONDITION. "
    "A matching word elsewhere in the note, belonging to a different problem, does NOT satisfy "
    "the axis -- judge the axis against the statement that actually concerns this condition.\n"
    "4. Do NOT report an axis that is genuinely documented for the condition.\n"
    "5. `note_quote` MUST be copied character-for-character from the note as the evidence for "
    "your observation. Never paraphrase, summarize, or invent it. An observation whose quote is "
    "not verbatim note text is discarded.\n"
    "6. `issue` is one sentence naming the specific gap.\n"
    "Return an empty list if the note has no gaps."
)

_VALIDATE_SYSTEM = (
    "You are validating CDI observations about ONE condition against the governing "
    "documentation. You are given CANDIDATE CLAUSES retrieved from the knowledge base -- "
    "these are the ONLY documents you may cite.\n"
    "Rules:\n"
    "1. Answer EVERY axis listed in the observations, in the same order. Judge each axis "
    "separately: a clause that governs one axis often says nothing about another.\n"
    "2. Return only clauses that genuinely govern or support that axis -- i.e. the clause "
    "actually instructs what must be documented for this condition and axis.\n"
    "3. `clause_id` MUST be copied exactly from the candidate list. Never return a "
    "clause_id that is not in the list, and never recall one from memory.\n"
    "4. `quote` MUST be copied character-for-character from that candidate's text. Never "
    "paraphrase. A quote that is not verbatim is discarded.\n"
    "5. If NONE of the candidates relate to an axis, return an empty supports list for "
    "it. Do not stretch a loosely-related clause into support -- an empty list is the "
    "correct, expected answer when the documentation is silent, and is reported to the "
    "user as \"no reference in the KB\"."
)


def _condition_catalogue(requirements: list[DiagnosisRequirement]) -> str:
    return "\n".join(
        f"- {req.condition} (also: {', '.join(req.synonyms)}) | axes: "
        + ", ".join(f"{rule.axis} [{rule.level}]" for rule in req.axes)
        for req in requirements
    )


def analyze_note(note_text: str, requirements: list[DiagnosisRequirement]) -> list[NoteObservation]:
    """Pass A: the model reads and analyzes the note. No KB text is sent here --
    this pass is pure clinical reading; validation against the documents is
    Pass B's job, per the KB-is-the-authority rule."""
    client = _make_client()
    response = client.messages.parse(
        model=ANTHROPIC_MODEL,
        max_tokens=16000,
        system=_ANALYZE_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"ALLOWED CONDITIONS:\n{_condition_catalogue(requirements)}\n\nNOTE:\n{note_text}",
        }],
        output_format=_Analysis,
    )
    parsed = response.parsed_output
    if parsed is None:  # truncated / unparseable structured output
        raise ValueError(f"analysis pass returned no parsable output (stop_reason={response.stop_reason})")
    return [
        NoteObservation(condition=o.condition, axis=o.axis, issue=o.issue, note_quote=o.note_quote)
        for o in parsed.observations
    ]


def group_for_validation(
    observations: list[NoteObservation],
) -> list[tuple[str, list[NoteObservation]]]:
    """Observations grouped by condition, in first-seen order.

    Pass B used to be one API call per OBSERVATION, so a condition with three gap
    axes paid three round trips over three heavily-overlapping candidate sets. One
    call per CONDITION sends the clause text once and asks all its questions
    together."""
    grouped: dict[str, list[NoteObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.condition, []).append(observation)
    return list(grouped.items())


def build_validation_content(clauses: list[Clause], observations_text: str) -> list[dict]:
    """Pass B user content as blocks, with the clause text marked cacheable.

    The candidate clause text is the bulk of the prompt and is stable across notes
    (retrieval is deterministic per condition/axis), so it carries a cache_control
    breakpoint. The observations block is per-note and deliberately sits AFTER it,
    uncached, so it cannot invalidate the cached prefix."""
    rendered = "\n\n".join(
        f"[{c.clause_id}] (page {c.page}, section: {c.section_title})\n{c.text}"
        for c in clauses
    )
    return [
        {"type": "text", "text": f"CANDIDATE CLAUSES:\n{rendered}",
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": observations_text},
    ]


def validate_against_kb(
    condition: str,
    observations: list[NoteObservation],
    candidates: list[Clause],
) -> dict[str, list[KbSupport]]:
    """Pass B: the model reads the RETRIEVED clause text and decides, per axis,
    whether the documentation actually governs the observation. An axis mapping to
    an empty list is a valid, expected outcome -- it becomes "no reference in the
    KB"."""
    if not candidates or not observations:
        return {}
    asked = "\n".join(
        f"- axis: {o.axis}\n  issue: {o.issue}\n  note evidence: {o.note_quote}"
        for o in observations
    )
    observations_text = f"CONDITION: {condition}\nOBSERVATIONS\n{asked}"
    response = _make_client().messages.parse(
        model=ANTHROPIC_MODEL,
        max_tokens=8000,
        system=_VALIDATE_SYSTEM,
        messages=[{"role": "user", "content": build_validation_content(candidates, observations_text)}],
        output_format=_Validation,
    )
    parsed = response.parsed_output
    if parsed is None:
        raise ValueError(f"validation pass returned no parsable output (stop_reason={response.stop_reason})")
    return {
        v.axis: [KbSupport(clause_id=s.clause_id, quote=s.quote) for s in v.supports]
        for v in parsed.validations
    }


def validate_all(
    items: list[tuple[str, list[NoteObservation], list[Clause]]],
    *,
    validator=None,
    max_workers: int = VALIDATION_CONCURRENCY,
) -> list[dict[str, list[KbSupport]]]:
    """Run Pass B for every (condition, observations, candidates) group concurrently,
    results in INPUT ORDER -- they are zipped back onto their groups by position, so
    an out-of-order result would attach one condition's authority to another.

    A validator that raises propagates and fails the whole stage rather than being
    swallowed into an empty support map. That is deliberate: empty means "the
    documents carry nothing on this point" and is reported to the user as such, so
    turning a transport failure into one would put a false statement about the KB in
    front of a clinician. Losing the batch to AuditResult.llm_error, with the
    deterministic findings still returned, is the honest failure."""
    validator = validator or validate_against_kb
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
        return list(pool.map(lambda item: validator(*item), items))


def run_llm_stage(
    note_text: str,
    requirements: list[DiagnosisRequirement],
    index: SearchIndex,
) -> list[ValidatedObservation]:
    """Analyze -> ground in the note -> retrieve -> validate against the KB.

    The KB is the validation authority: nothing the model observed is reported with
    authority it did not earn against retrieved clause text. Observations the
    documents do not cover still come back (with empty supports) so the audit can
    report them as "no reference in the KB".

    Retrieval stays per (condition, axis) -- the candidate set must not depend on how
    many axes happen to be asked -- but the union of a condition's candidates is sent
    once, and its axes are judged in a single call."""
    by_condition = {req.condition: req for req in requirements}
    grounded = keep_grounded(analyze_note(note_text, requirements), note_text, by_condition)
    store = ClauseStore(config.KB_DB)
    try:
        items: list[tuple[str, list[NoteObservation], list[Clause]]] = []
        for condition, observations in group_for_validation(grounded):
            requirement = by_condition[condition]
            clause_ids: list[str] = []
            for observation in observations:
                for clause_id in retrieve_candidates(index, observation, requirement):
                    if clause_id not in clause_ids:
                        clause_ids.append(clause_id)
            clauses = [c for c in (store.get(cid) for cid in clause_ids) if c is not None]
            items.append((condition, observations, clauses))

        validated: list[ValidatedObservation] = []
        for (_condition, observations, clauses), by_axis in zip(items, validate_all(items), strict=True):
            allowed = [c.clause_id for c in clauses]
            for observation in observations:
                supports = keep_candidate_supports(by_axis.get(observation.axis, []), allowed)
                validated.append(ValidatedObservation(observation=observation, supports=supports))
        return validated
    finally:
        store.close()
