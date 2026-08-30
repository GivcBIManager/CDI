"""Optional LLM stage: infer conditions that are treated but never named
(e.g. oxygen support without 'respiratory failure' — proposal top-20 rows
1, 7, 9, 12, 19). The model selects only from the known condition list;
anything else is discarded. Citations still come exclusively from the
requirement model + clause store, so this stage cannot fabricate authority.
"""

import ssl

import anthropic
from anthropic import DefaultHttpxClient
from pydantic import BaseModel

from cdi_kb.config import ANTHROPIC_MODEL


def _make_client() -> anthropic.Anthropic:
    """Client with an explicitly built default SSL context.

    This machine's Python carries a pip_system_certs bootstrap that patches ssl
    with pip's vendored truststore; httpx2 then layers the standalone
    truststore package on top, and the double patch recurses infinitely inside
    SSLContext.verify_mode. Passing an explicit context sidesteps httpx2's own
    truststore path. Portable: on unpatched machines this is simply the
    standard default context.
    """
    return anthropic.Anthropic(http_client=DefaultHttpxClient(verify=ssl.create_default_context()))


class ImplicitFinding(BaseModel):
    condition: str
    evidence: str


class ImplicitFindings(BaseModel):
    findings: list[ImplicitFinding]


_SYSTEM = (
    "You are a clinical documentation integrity checker. Given a clinical note, "
    "identify conditions from the ALLOWED LIST ONLY that are clinically evident "
    "(e.g. being treated) but never named in the note. Return the exact condition "
    "string from the list and the note evidence. If none, return an empty list. "
    "Never return a condition that is already explicitly named in the note."
)


def filter_to_known(findings: list[ImplicitFinding], known: tuple[str, ...]) -> list[ImplicitFinding]:
    allowed = set(known)
    return [f for f in findings if f.condition in allowed]


def infer_implicit_conditions(note_text: str, known_conditions: tuple[str, ...]) -> list[ImplicitFinding]:
    client = _make_client()
    response = client.messages.parse(
        model=ANTHROPIC_MODEL,
        max_tokens=2000,
        system=_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"ALLOWED LIST: {list(known_conditions)}\n\nNOTE:\n{note_text}",
        }],
        output_format=ImplicitFindings,
    )
    return filter_to_known(response.parsed_output.findings, known_conditions)
