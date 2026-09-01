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


# Matrix rows: one per finding type, in a fixed DISPLAY order rather than the
# order run_audit happens to append them. Deterministic, citation-anchored
# findings read first; the inferred ones (which can carry "no reference in the
# KB") read last, so a reviewer works down from the most defensible.
FINDING_TYPE_LABELS: dict[str, str] = {
    "specificity_gap": "Diagnosis specificity",
    "completeness_gap": "Document completeness",
    "necessity_mismatch": "Order necessity",
    "provider_confirmation": "Provider confirmation",
    "conflicting_documentation": "Conflicting documentation",
    "copy_forward": "Documentation integrity",
    "inferred_gap": "Inferred condition (LLM)",
}

_SEVERITIES = ("required", "recommended")


def build_matrix(findings) -> dict:
    """Findings as a matrix: severity down the side, finding type across the top.

    Severity is the axis a reviewer triages on first, so it runs down the side
    where the eye starts, and finding type -- the "what kind of problem is this"
    axis -- runs across the top.

    Columns cover only the finding types PRESENT; with seven possible types most
    are absent from any given note and an empty column is width a reviewer pays
    for and learns nothing from. Both severity ROWS always render, empty or not:
    "Required: none" is a fact worth stating rather than leaving to be inferred
    from a missing row.

    `cells` is positional -- one entry per column, in column order -- so the
    renderer can walk rows and columns together without re-grouping.

    A finding type with no label would render as a bare identifier in the header,
    so any unlabelled type is appended at the end under its own identifier rather
    than being silently dropped.
    """
    by_type: dict[str, list] = {}
    for finding in findings:
        by_type.setdefault(finding.finding_type, []).append(finding)
    ordered = [t for t in FINDING_TYPE_LABELS if t in by_type]
    ordered += [t for t in by_type if t not in FINDING_TYPE_LABELS]

    columns = [{"finding_type": finding_type,
                "label": FINDING_TYPE_LABELS.get(finding_type, finding_type),
                "count": len(by_type[finding_type])}
               for finding_type in ordered]
    rows = []
    for severity in _SEVERITIES:
        cells = [[dataclasses.asdict(f) for f in by_type[finding_type]
                  if f.severity == severity]
                 for finding_type in ordered]
        rows.append({"severity": severity,
                     "count": sum(len(cell) for cell in cells),
                     "cells": cells})
    return {"columns": columns, "rows": rows}


@app.post("/api/audit")
def api_audit(request: AuditRequest) -> dict:
    result = run_audit(request.note_text, doc_type=request.doc_type, use_llm=request.use_llm)
    return {"findings": [dataclasses.asdict(f) for f in result.findings],
            "matrix": build_matrix(result.findings),
            "dropped_citations": result.dropped_citations,
            "active_doc_type": result.active_doc_type,
            "llm_error": result.llm_error}


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
 .finding{border-left:4px solid #b91c1c;background:#fef2f2;margin:.5rem 0;padding:.5rem .7rem;border-radius:4px}
 .finding.recommended{border-color:#b45309;background:#fffbeb}
 .unref{color:#6b7280;font-style:italic;margin-top:.3rem}
 .cite{color:#555;font-size:.8rem;margin-top:.3rem;word-break:break-word}
 button{padding:.5rem 1.2rem;font-size:1rem;margin-top:.5rem}
 #doctype-result{font-weight:600;margin:.8rem 0 0}
 /* Matrix: severity down the side, finding type across the top. Column count
    varies with the note, so the grid is built from --cols and the whole thing
    scrolls sideways rather than crushing cells at narrow widths. */
 .mwrap{overflow-x:auto;margin-top:1rem}
 .matrix{display:grid;grid-template-columns:minmax(7rem,auto) repeat(var(--cols),minmax(15rem,1fr));gap:.5rem;align-items:start}
 .mhead{font-weight:600;padding:.4rem .2rem;border-bottom:2px solid #d1d5db;line-height:1.25}
 .mhead .n{display:block;font-weight:400;color:#6b7280;font-size:.8rem}
 .rowlabel{font-weight:600;padding:.5rem .2rem;border-top:1px solid #e5e7eb;line-height:1.25}
 .rowlabel.required{color:#b91c1c}
 .rowlabel.recommended{color:#b45309}
 .rowlabel .n{display:block;font-weight:400;color:#6b7280;font-size:.8rem}
 .cell{border-top:1px solid #e5e7eb;padding-top:.25rem;min-height:1.5rem}
 .cell.empty{color:#9ca3af;font-size:.85rem;padding:.5rem .2rem}
 @media(max-width:52rem){
   .matrix{grid-template-columns:1fr}
   .mhead{display:none}
   .cell:before{content:attr(data-label);display:block;font-weight:600;font-size:.8rem;color:#6b7280}
   .cell.empty{display:none}
 }
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

  if(d.matrix.columns.length === 0){
    const none = document.createElement('p');
    none.textContent = 'No findings.';
    out.appendChild(none);
  } else {
    const wrap = document.createElement('div');
    wrap.className = 'mwrap';
    const grid = document.createElement('div');
    grid.className = 'matrix';
    grid.style.setProperty('--cols', d.matrix.columns.length);
    // Header: an empty corner cell, then one heading per finding type.
    let head = '<div class="mhead"></div>';
    for(const col of d.matrix.columns){
      head += '<div class="mhead">'+esc(col.label)+'<span class="n">'+col.count+'</span></div>';
    }
    grid.innerHTML = head;
    for(const row of d.matrix.rows){
      const label = document.createElement('div');
      label.className = 'rowlabel '+esc(row.severity);
      label.innerHTML = esc(row.severity === 'required' ? 'Required' : 'Recommended')
        + '<span class="n">'+row.count+'</span>';
      grid.appendChild(label);
      row.cells.forEach(function(cell, n){
        const div = document.createElement('div');
        // Carries the COLUMN label: below 52rem the header row is hidden and
        // each cell announces which finding type it belongs to.
        div.dataset.label = d.matrix.columns[n].label;
        if(cell.length === 0){
          div.className = 'cell empty';
          div.textContent = '—';
        } else {
          div.className = 'cell';
          for(const f of cell) div.appendChild(renderFinding(f));
        }
        grid.appendChild(div);
      });
    }
    wrap.appendChild(grid);
    out.appendChild(wrap);
  }

  if(d.llm_error){
    const warn = document.createElement('p');
    warn.className = 'unref';
    warn.textContent = 'LLM stage unavailable ('+d.llm_error+') — deterministic findings only';
    out.appendChild(warn);
  }
}

// Headline wording mirrors cli.format_finding: only a specificity or
// completeness gap is literally something MISSING, and reading the integrity
// findings that way sends the reviewer after the wrong thing.
function headline(f){
  if(f.finding_type === 'provider_confirmation')
    return esc(f.condition)+' — not confirmed by the treating doctor';
  if(f.finding_type === 'copy_forward')
    return 'content carried forward from an earlier note';
  if(f.finding_type === 'conflicting_documentation')
    return esc(f.condition)+' — conflicting '+esc(f.axis.replace(/^conflicting_/,''))+' documented';
  return '<strong>'+esc(f.condition)+'</strong> — missing <em>'+esc(f.axis)+'</em>';
}

function renderFinding(f){
  const div = document.createElement('div');
  // esc() even here: className is a property assignment rather than an HTML
  // parse, but the page's rule is that EVERY server-supplied field passes
  // through the escaper, so no field is left as the one exception to audit.
  div.className = 'finding '+esc(f.severity);
  div.innerHTML = headline(f)
    +'<div>'+esc(f.recommendation)+'</div>'
    // A finding the documents did not support is labelled, never left looking
    // like a cited one. kb_status is server-side text, still escaped.
    +(f.kb_status === 'supported' ? ''
      : '<div class="unref">'+esc(f.kb_status)+' — evidence: "'+esc(f.evidence_excerpt)+'"</div>')
    +f.citations.map(c=>'<div class="cite">source: '+esc(c.clause_id)+' (p.'+esc(c.page)+') — "'+esc(c.quote)+'"</div>').join('');
  return div;
}
</script></body></html>"""

_PAGE = _PAGE_TEMPLATE.replace("__DOC_TYPE_OPTIONS__", _DOC_TYPE_OPTIONS)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE
