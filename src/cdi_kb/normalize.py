"""Text normalization and fuzzy quote matching.

find_quote is the citation firewall primitive (proposal section 2.2): a quote
"matches" a source only if it appears verbatim after normalization, or at
>= threshold similarity in a sliding window. Callers must drop any citation
whose quote does not match.
"""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

_WHITESPACE = re.compile(r"\s+")
_CHAR_MAP = str.maketrans({
    "“": '"', "”": '"', "‘": "'", "’": "'",
    "–": "-", "—": "-", " ": " ", "ﬁ": "fi", "ﬂ": "fl",
})


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_CHAR_MAP)
    return _WHITESPACE.sub(" ", text).strip().lower()


@dataclass(frozen=True)
class QuoteMatch:
    found: bool
    score: float


def find_quote(quote: str, source: str, threshold: float = 0.95) -> QuoteMatch:
    norm_quote, norm_source = normalize(quote), normalize(source)
    if not norm_quote:
        return QuoteMatch(found=False, score=0.0)
    if norm_quote in norm_source:
        return QuoteMatch(found=True, score=1.0)
    window = len(norm_quote) + len(norm_quote) // 10
    step = max(1, len(norm_quote) // 4)
    best = 0.0
    for start in range(0, max(1, len(norm_source) - len(norm_quote) + 1), step):
        ratio = SequenceMatcher(None, norm_quote, norm_source[start : start + window]).ratio()
        best = max(best, ratio)
        if best >= 0.999:
            break
    return QuoteMatch(found=best >= threshold, score=round(best, 4))
