"""Paste-a-note demo UI. Single page, no external assets."""

import dataclasses

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from cdi_kb import config
from cdi_kb.audit import run_audit
from cdi_kb.index import SearchIndex

app = FastAPI(title="CDI Audit Demo")


class AuditRequest(BaseModel):
    note_text: str
    use_llm: bool = False


@app.post("/api/audit")
def api_audit(request: AuditRequest) -> dict:
    result = run_audit(request.note_text, use_llm=request.use_llm)
    return {"findings": [dataclasses.asdict(f) for f in result.findings],
            "dropped_citations": result.dropped_citations}


@app.get("/api/search")
def api_search(q: str) -> dict:
    index = SearchIndex(config.KB_DB)
    hits = index.search(q, limit=10)
    index.close()
    return {"hits": [dataclasses.asdict(h) for h in hits]}


_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>CDI Audit Demo</title>
<style>
 body{font-family:system-ui;margin:2rem;max-width:60rem}
 textarea{width:100%;height:12rem;font-size:1rem}
 .finding{border-left:4px solid #b91c1c;background:#fef2f2;margin:.6rem 0;padding:.6rem .8rem;border-radius:4px}
 .finding.recommended{border-color:#b45309;background:#fffbeb}
 .cite{color:#555;font-size:.85rem;margin-top:.3rem}
 button{padding:.5rem 1.2rem;font-size:1rem;margin-top:.5rem}
</style></head><body>
<h1>CDI Audit Demo</h1>
<p>Paste a clinical note. Findings cite the CDI booklet verbatim — no citation, no finding.</p>
<textarea id="note" placeholder="e.g. 62M admitted with fluid overload. Background: CKD..."></textarea><br>
<label><input type="checkbox" id="llm"> infer treated-but-unnamed conditions (LLM)</label><br>
<button onclick="audit()">Audit note</button>
<div id="out"></div>
<script>
async function audit(){
  const r = await fetch('/api/audit',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({note_text:document.getElementById('note').value,
                         use_llm:document.getElementById('llm').checked})});
  const d = await r.json();
  const out = document.getElementById('out');
  out.innerHTML = '<h2>'+d.findings.length+' finding(s)</h2>';
  for(const f of d.findings){
    const div = document.createElement('div');
    div.className = 'finding '+f.severity;
    div.innerHTML = '<strong>'+f.condition+'</strong> — missing <em>'+f.axis+'</em> ('+f.severity+')'
      +'<div>'+f.recommendation+'</div>'
      +f.citations.map(c=>'<div class="cite">source: '+c.clause_id+' (p.'+c.page+') — "'+c.quote+'"</div>').join('');
    out.appendChild(div);
  }
}
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE
