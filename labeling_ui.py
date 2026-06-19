"""
OBSIDIAN — Ground Truth Labeling UI (Stage 7)
Self-contained HTML for the /admin/labeling page.
Renders pending predictions and the right input control per type.
"""

LABELING_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OBSIDIAN // Ground Truth Labeling — CAP 12</title>
<style>
:root{
  --black:#040810; --blue:#A855F7; --ice:#eaf6ff; --red:#FF0033;
  --amber:#ffb020; --green:#23d18b;
  --panel:rgba(18,8,38,0.78); --panel-2:rgba(14,6,32,0.9);
  --line:rgba(168,85,247,0.22); --line-b:rgba(168,85,247,0.5);
  --txt:#d6c9ee; --txt-dim:#9b87c4; --txt-faint:#6a548c;
}
*{margin:0;padding:0;box-sizing:border-box}
body{background:#02060e;color:var(--txt);font-family:'Rajdhani',system-ui,sans-serif;
  background-image:radial-gradient(1000px 600px at 78% -8%,rgba(90,45,200,.18),transparent 55%),
    linear-gradient(180deg,#02060e,#040c18 60%,#02060e);min-height:100vh;padding:24px}
.head{display:flex;align-items:center;justify-content:space-between;
  border-bottom:1px solid var(--line-b);padding-bottom:14px;margin-bottom:20px}
.head h1{font-size:20px;font-weight:900;letter-spacing:.28em;color:var(--ice);
  text-shadow:0 0 22px rgba(168,85,247,.5)}
.head .sub{font-size:10px;letter-spacing:.3em;color:var(--blue);
  text-transform:uppercase;margin-top:4px}
.head a{color:var(--txt-dim);font-size:11px;text-decoration:none;letter-spacing:.1em}
.head a:hover{color:var(--ice)}
.stats{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}
.stat{background:var(--panel-2);border:1px solid var(--line);padding:10px 16px;min-width:120px}
.stat .n{font-size:24px;font-weight:700;color:var(--ice);font-family:monospace}
.stat .k{font-size:9px;letter-spacing:.2em;color:var(--txt-faint);text-transform:uppercase;margin-top:2px}
.tabs{display:flex;gap:8px;margin-bottom:16px}
.tab{background:var(--panel-2);border:1px solid var(--line);color:var(--txt-dim);
  padding:8px 18px;cursor:pointer;font-size:12px;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;transition:.15s}
.tab.active{background:var(--blue);color:#02060e;border-color:var(--blue)}
.card{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--blue);
  padding:16px 18px;margin-bottom:14px}
.card .ptype{font-size:9px;font-weight:700;letter-spacing:.16em;color:var(--blue);
  text-transform:uppercase}
.card .hl{font-size:15px;font-weight:600;color:var(--ice);margin:6px 0 4px}
.card .meta{font-size:11px;color:var(--txt-faint);font-family:monospace;margin-bottom:10px}
.predbox{background:var(--panel-2);border:1px solid var(--line);padding:10px 12px;
  margin:10px 0;font-family:monospace;font-size:12px;color:var(--txt-dim);
  white-space:pre-wrap;word-break:break-word}
.qlabel{font-size:13px;color:var(--ice);font-weight:600;margin:12px 0 8px}
.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
input[type=number],input[type=text],select{background:var(--panel-2);border:1px solid var(--line);
  color:var(--ice);padding:8px 11px;font-family:'Rajdhani',sans-serif;font-size:13px;
  font-weight:500;outline:none;border-radius:2px}
input:focus,select:focus{border-color:var(--blue)}
.choice{display:flex;gap:8px;flex-wrap:wrap}
.choice button{background:var(--panel-2);border:1px solid var(--line);color:var(--txt-dim);
  padding:8px 14px;cursor:pointer;font-size:12px;font-weight:600;letter-spacing:.05em;transition:.12s}
.choice button.sel{background:var(--blue);color:#02060e;border-color:var(--blue)}
.boolrow{display:flex;gap:8px}
.boolrow button{background:var(--panel-2);border:1px solid var(--line);color:var(--txt-dim);
  padding:8px 18px;cursor:pointer;font-size:12px;font-weight:700;transition:.12s}
.boolrow button.yes.sel{background:var(--green);color:#02060e;border-color:var(--green)}
.boolrow button.no.sel{background:var(--red);color:#fff;border-color:var(--red)}
.submit{background:var(--blue);color:#02060e;border:none;padding:9px 20px;cursor:pointer;
  font-weight:700;font-size:12px;letter-spacing:.1em;text-transform:uppercase;border-radius:2px;
  transition:.15s}
.submit:hover{filter:brightness(1.12)}
.submit:disabled{opacity:.5;cursor:not-allowed}
.who{display:flex;gap:8px;align-items:center;margin-bottom:16px}
.who label{font-size:11px;color:var(--txt-dim);letter-spacing:.08em;text-transform:uppercase}
.empty{text-align:center;padding:50px;color:var(--txt-faint);font-size:14px;letter-spacing:.1em}
.toast{position:fixed;bottom:20px;right:20px;background:var(--green);color:#02060e;
  padding:12px 20px;font-weight:700;border-radius:3px;opacity:0;transform:translateY(10px);
  transition:.25s;pointer-events:none}
.toast.show{opacity:1;transform:none}
.toast.err{background:var(--red);color:#fff}
.labeled-row{font-size:12px;display:flex;gap:14px;padding:8px 0;border-bottom:1px solid var(--line);
  color:var(--txt-dim);flex-wrap:wrap}
.labeled-row b{color:var(--ice)}
</style>
</head>
<body>
<div class="head">
  <div>
    <h1>OBSIDIAN // GROUND TRUTH</h1>
    <div class="sub">CAP 12 · Calibration Labeling · Stage 7</div>
  </div>
  <a href="/admin/routing-simulator">← Command Center</a>
</div>

<div class="who">
  <label>Labeling as:</label>
  <select id="analyst">
    <option value="Ankit">Ankit (COO)</option>
    <option value="Adi">Adi (CEO)</option>
    <option value="Shalini">Shalini (Analyst)</option>
  </select>
</div>

<div class="stats" id="stats"></div>

<div class="tabs">
  <div class="tab active" data-tab="pending" id="tabPending">Pending</div>
  <div class="tab" data-tab="labeled" id="tabLabeled">Labeled</div>
</div>

<div id="pendingView"></div>
<div id="labeledView" style="display:none"></div>

<div class="toast" id="toast"></div>

<script>
const esc=s=>(s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const draft={}; // prediction_id -> outcome under construction

function showToast(msg, err){
  const t=document.getElementById("toast");
  t.textContent=msg; t.className="toast show"+(err?" err":"");
  setTimeout(()=>t.className="toast",2200);
}

function fmtPredicted(type, pv){
  try{
    if(type==="severity") return "Predicted severity: "+pv.severity_score;
    if(type==="duration") return "Predicted duration — modal:"+(pv.modal_days||"?")+"d  min:"+(pv.min_days||"?")+"  max:"+(pv.max_days||"?");
    if(type==="scenario"){
      return (pv.scenarios||[]).map(s=>s.scenario+": "+Math.round(s.probability*100)+"% ("+s.timeline_days+"d)").join("\n");
    }
    if(type==="industry_impact"){
      return (pv.impacts||[]).map(i=>i.industry+": impact "+i.predicted_impact+"/10").join("\n");
    }
  }catch(e){}
  return JSON.stringify(pv);
}

function renderControl(p){
  const sc=p.outcome_schema||{};
  const pid=p.prediction_id;
  if(sc.input==="number"){
    return '<input type="number" id="in_'+pid+'" placeholder="enter number" '+
      'oninput="draft[\''+pid+'\']={'+JSON.stringify(sc.field).slice(1,-1)+':parseFloat(this.value)}">';
  }
  if(sc.input==="choice"){
    return '<div class="choice" id="ch_'+pid+'">'+
      sc.choices.map(c=>'<button onclick="pickChoice(\''+pid+'\',\''+c+'\',\''+sc.field+'\',this)">'+c+'</button>').join("")+'</div>';
  }
  if(sc.input==="boolean"){
    return '<div class="boolrow" id="bl_'+pid+'">'+
      '<button class="yes" onclick="pickBool(\''+pid+'\',true,\''+sc.field+'\',this)">YES — impacted</button>'+
      '<button class="no" onclick="pickBool(\''+pid+'\',false,\''+sc.field+'\',this)">NO — not impacted</button></div>';
  }
  return '<input type="text" id="in_'+pid+'" placeholder="outcome" '+
    'oninput="draft[\''+pid+'\']={value:this.value}">';
}

function pickChoice(pid,val,field,btn){
  draft[pid]={[field]:val};
  btn.parentNode.querySelectorAll("button").forEach(b=>b.classList.remove("sel"));
  btn.classList.add("sel");
}
function pickBool(pid,val,field,btn){
  draft[pid]={[field]:val};
  btn.parentNode.querySelectorAll("button").forEach(b=>b.classList.remove("sel"));
  btn.classList.add("sel");
}

async function loadPending(){
  const r=await fetch("/api/labeling/pending").then(x=>x.json());
  const v=document.getElementById("pendingView");
  if(!r.pending.length){ v.innerHTML='<div class="empty">NO PREDICTIONS AWAITING LABELS</div>'; return r; }
  v.innerHTML=r.pending.map(p=>
    '<div class="card">'+
      '<div class="ptype">'+esc(p.prediction_type)+' · horizon '+p.horizon_days+'d · confidence '+p.confidence_score+'%</div>'+
      '<div class="hl">'+esc(p.headline||"(event)")+'</div>'+
      '<div class="meta">made '+(p.made_at||"").slice(0,10)+' · scope '+esc(p.geographic_scope||"—")+'</div>'+
      '<div class="predbox">'+esc(fmtPredicted(p.prediction_type,p.predicted_value))+'</div>'+
      '<div class="qlabel">'+esc((p.outcome_schema||{}).label||"Record outcome")+'</div>'+
      '<div class="controls">'+renderControl(p)+'</div>'+
      '<input type="text" id="notes_'+p.prediction_id+'" placeholder="notes (optional)" style="width:100%;margin-bottom:10px">'+
      '<button class="submit" onclick="submitLabel(\''+p.prediction_id+'\')">Save Outcome</button>'+
    '</div>'
  ).join("");
  return r;
}

async function loadLabeled(){
  const r=await fetch("/api/labeling/labeled").then(x=>x.json());
  const v=document.getElementById("labeledView");
  if(!r.labeled.length){ v.innerHTML='<div class="empty">NO LABELS RECORDED YET</div>'; return r; }
  v.innerHTML=r.labeled.map(l=>
    '<div class="labeled-row">'+
      '<b>'+esc(l.prediction_type)+'</b>'+
      '<span>'+esc(l.headline||"")+'</span>'+
      '<span>outcome: '+esc(JSON.stringify(l.outcome_value))+'</span>'+
      '<span>by '+esc(l.labeled_by)+'</span>'+
      '<span>'+(l.labeled_at||"").slice(0,10)+'</span>'+
    '</div>'
  ).join("");
  return r;
}

async function refreshStats(){
  const [p,l]=await Promise.all([
    fetch("/api/labeling/pending").then(x=>x.json()),
    fetch("/api/labeling/labeled").then(x=>x.json())
  ]);
  document.getElementById("stats").innerHTML=
    '<div class="stat"><div class="n">'+p.count+'</div><div class="k">Pending</div></div>'+
    '<div class="stat"><div class="n">'+l.count+'</div><div class="k">Labeled</div></div>'+
    '<div class="stat"><div class="n">'+(p.count+l.count)+'</div><div class="k">Total Predictions</div></div>';
}

async function submitLabel(pid){
  const outcome=draft[pid];
  if(!outcome || Object.values(outcome).some(v=>v===undefined||v===""||(typeof v==="number"&&isNaN(v)))){
    showToast("Enter an outcome first",true); return;
  }
  const analyst=document.getElementById("analyst").value;
  const notesEl=document.getElementById("notes_"+pid);
  const body={prediction_id:pid, outcome_value:outcome, labeled_by:analyst,
    notes: notesEl? notesEl.value : null};
  try{
    const res=await fetch("/api/labeling/submit",{method:"POST",
      headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}).then(x=>x.json());
    if(res.ok){ showToast("Outcome saved ✓"); delete draft[pid];
      await loadPending(); await refreshStats(); }
    else showToast(res.detail||res.error||"Save failed",true);
  }catch(e){ showToast("Network error",true); }
}

document.getElementById("tabPending").onclick=()=>{
  document.getElementById("tabPending").classList.add("active");
  document.getElementById("tabLabeled").classList.remove("active");
  document.getElementById("pendingView").style.display="";
  document.getElementById("labeledView").style.display="none";
};
document.getElementById("tabLabeled").onclick=async()=>{
  document.getElementById("tabLabeled").classList.add("active");
  document.getElementById("tabPending").classList.remove("active");
  document.getElementById("labeledView").style.display="";
  document.getElementById("pendingView").style.display="none";
  await loadLabeled();
};

loadPending(); refreshStats();
</script>
</body>
</html>
"""
