"""Paste-a-note demo UI. Single page, no external assets."""

import dataclasses
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from cdi_kb import config
from cdi_kb.audit import run_audit
from cdi_kb.index import SearchIndex
from cdi_kb.requirements_model import DOC_TYPES

# Built from DOC_TYPES (the single source of truth) rather than hardcoded, so
# the accepted values can never drift from the CLI's --doc-type choices.
# Deliberately excludes "any" -- that's the internal auto-detect fallback
# value, never a valid client-supplied choice (the dropdown only offers Auto,
# which sends None/omits the field, plus the 5 concrete types).
_DocTypeChoice = Literal[DOC_TYPES]

app = FastAPI(title="CDI Audit Demo")

# Human-readable labels for the "Document type" dropdown -- keys/order come
# from DOC_TYPES (the same 5 concrete types the CLI's --doc-type accepts).
_DOC_TYPE_LABELS: dict[str, str] = {
    "discharge_summary": "Discharge summary",
    "admission_note": "Admission note",
    "progress_note": "Progress note",
    "emergency_note": "Emergency note",
    "diagnosis_list": "Diagnosis list",
}


class AuditRequest(BaseModel):
    note_text: str
    # None (omitted or null) means Auto -- run_audit auto-detects the doc type
    # from the note's own shape. A concrete value overrides detection, same
    # as the CLI's --doc-type. Restricted to exactly the 5 DOC_TYPES (never
    # "any", never arbitrary text) -- FastAPI/pydantic returns 422 on anything
    # else, closing the reflected-XSS path where an unvalidated doc_type would
    # otherwise come back verbatim in active_doc_type for the page to render.
    doc_type: _DocTypeChoice | None = None
    use_llm: bool = False


@app.post("/api/audit")
def api_audit(request: AuditRequest) -> dict:
    result = run_audit(request.note_text, doc_type=request.doc_type, use_llm=request.use_llm)
    return {"findings": [dataclasses.asdict(f) for f in result.findings],
            "dropped_citations": result.dropped_citations,
            "active_doc_type": result.active_doc_type}


@app.get("/api/search")
def api_search(q: str) -> dict:
    index = SearchIndex(config.KB_DB)
    hits = index.search(q, limit=10)
    index.close()
    return {"hits": [dataclasses.asdict(h) for h in hits]}


_DOC_TYPE_OPTIONS = '<option value="">Auto</option>' + "".join(
    f'<option value="{doc_type}">{_DOC_TYPE_LABELS[doc_type]}</option>' for doc_type in DOC_TYPES
)

_PAGE_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><title>CDI Audit Demo</title>
<style>
 body{font-family:system-ui;margin:2rem;max-width:60rem}
 textarea{width:100%;height:12rem;font-size:1rem}
 select{font-size:1rem;padding:.2rem}
 .finding{border-left:4px solid #b91c1c;background:#fef2f2;margin:.6rem 0;padding:.6rem .8rem;border-radius:4px}
 .finding.recommended{border-color:#b45309;background:#fffbeb}
 .cite{color:#555;font-size:.85rem;margin-top:.3rem}
 button{padding:.5rem 1.2rem;font-size:1rem;margin-top:.5rem}
 #doctype-result{font-weight:600;margin:.8rem 0 0}
</style></head><body>
<h1>CDI Audit Demo</h1>
<p>Paste a clinical note. Findings cite the CDI booklet and CHI guidelines verbatim — no citation, no finding.</p>
<textarea id="note" placeholder="e.g. 62M admitted with fluid overload. Background: CKD..."></textarea><br>
<label>Document type: <select id="doctype">__DOC_TYPE_OPTIONS__</select></label><br>
<label><input type="checkbox" id="llm"> infer treated-but-unnamed conditions (LLM)</label><br>
<button onclick="audit()">Audit note</button>
<div id="out"></div>
<script>
// Every field below originates from the server response (findings are
// KB-authored today, but nothing here should ever be trusted to be safe
// markup) -- escape before string-concatenating into innerHTML.
function esc(s){
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
async function audit(){
  const docType = document.getElementById('doctype').value || null;
  const r = await fetch('/api/audit',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({note_text:document.getElementById('note').value,
                         doc_type:docType,
                         use_llm:document.getElementById('llm').checked})});
  const d = await r.json();
  const out = document.getElementById('out');
  out.innerHTML = '<p id="doctype-result">Detected/selected type: '+esc(d.active_doc_type)+'</p>'
    +'<h2>'+d.findings.length+' finding(s)</h2>';
  for(const f of d.findings){
    const div = document.createElement('div');
    div.className = 'finding '+f.severity;
    div.innerHTML = '<strong>'+esc(f.condition)+'</strong> — missing <em>'+esc(f.axis)+'</em> ('+esc(f.severity)+')'
      +'<div>'+esc(f.recommendation)+'</div>'
      +f.citations.map(c=>'<div class="cite">source: '+esc(c.clause_id)+' (p.'+esc(c.page)+') — "'+esc(c.quote)+'"</div>').join('');
    out.appendChild(div);
  }
}
</script></body></html>"""

_PAGE = _PAGE_TEMPLATE.replace("__DOC_TYPE_OPTIONS__", _DOC_TYPE_OPTIONS)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE
