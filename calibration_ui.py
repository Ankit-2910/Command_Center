"""
OBSIDIAN — Calibration Dashboard UI (Stage 8)
Self-contained HTML for /admin/calibration.
Shows the 4 metric cards + calibration curve, with honest low-data messaging.
"""

CALIBRATION_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OBSIDIAN // Calibration Metrics — CAP 12</title>
<style>
:root{
  --blue:#A855F7; --ice:#eaf6ff; --red:#FF0033; --amber:#ffb020; --green:#23d18b;
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
.head .sub{font-size:10px;letter-spacing:.3em;color:var(--blue);text-transform:uppercase;margin-top:4px}
.head a{color:var(--txt-dim);font-size:11px;text-decoration:none;letter-spacing:.1em}
.head a:hover{color:var(--ice)}
.banner{background:rgba(168,85,247,.08);border:1px solid var(--line);border-left:3px solid var(--blue);
  padding:12px 16px;margin-bottom:20px;font-size:13px;color:var(--txt-dim);line-height:1.5}
.banner b{color:var(--ice)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}
.metric{background:var(--panel);border:1px solid var(--line);padding:16px 18px;position:relative}
.metric .label{font-size:9px;letter-spacing:.14em;color:var(--txt-faint);text-transform:uppercase}
.metric .val{font-size:34px;font-weight:700;color:var(--ice);font-family:monospace;line-height:1.1;margin:8px 0 4px}
.metric .val.none{color:var(--txt-faint);font-size:20px}
.metric .n{font-size:11px;color:var(--txt-dim);font-family:monospace}
.metric .flag{font-size:8px;letter-spacing:.1em;text-transform:uppercase;padding:2px 7px;
  border-radius:2px;display:inline-block;margin-top:8px;font-weight:700}
.flag.stable{background:var(--green);color:#02060e}
.flag.unstable{border:1px solid var(--amber);color:var(--amber)}
.section{background:var(--panel);border:1px solid var(--line);padding:18px;margin-bottom:20px}
.section h2{font-size:12px;letter-spacing:.16em;color:var(--blue);text-transform:uppercase;margin-bottom:14px}
.curve-row{display:flex;align-items:center;gap:12px;margin-bottom:8px;font-size:12px}
.curve-band{width:70px;font-family:monospace;color:var(--txt-dim)}
.curve-track{flex:1;height:22px;background:var(--panel-2);position:relative;border:1px solid var(--line)}
.curve-claimed{position:absolute;top:0;height:100%;width:2px;background:var(--amber);z-index:2}
.curve-observed{position:absolute;top:0;height:100%;background:var(--blue);opacity:.6}
.curve-meta{width:140px;font-family:monospace;font-size:11px;color:var(--txt-dim);text-align:right}
.legend{display:flex;gap:18px;margin-top:12px;font-size:11px;color:var(--txt-dim)}
.legend span{display:flex;align-items:center;gap:6px}
.legend i{width:12px;height:12px;display:inline-block}
.empty{text-align:center;padding:40px;color:var(--txt-faint);font-size:13px;letter-spacing:.08em}
.explain{font-size:12px;color:var(--txt-faint);line-height:1.6;margin-top:8px}
</style>
</head>
<body>
<div class="head">
  <div>
    <h1>OBSIDIAN // CALIBRATION</h1>
    <div class="sub">CAP 12 · Prediction Accuracy Metrics · Stage 8</div>
  </div>
  <a href="/admin/labeling">← Labeling Tool</a>
</div>

<div id="banner" class="banner">Loading calibration metrics…</div>

<div class="grid" id="metricGrid"></div>

<div class="section">
  <h2>Calibration Curve — Claimed vs Observed Confidence</h2>
  <div id="curve"></div>
  <div class="legend">
    <span><i style="background:var(--amber)"></i> Claimed confidence (what the model said)</span>
    <span><i style="background:var(--blue);opacity:.6"></i> Observed hit-rate (what actually happened)</span>
  </div>
  <div class="explain">A well-calibrated engine has the blue bar reaching the amber line:
    when it claims 70% confidence, outcomes prove true ~70% of the time.</div>
</div>

<script>
function metricCard(key, m){
  const hasVal = m.value !== null && m.value !== undefined;
  const valStr = hasVal ? m.value : "—";
  const flag = m.count === 0 ? "" :
    (m.stable ? '<span class="flag stable">stable</span>'
              : '<span class="flag unstable">need '+(30-m.count>0?30-m.count:0)+' more</span>');
  return '<div class="metric">'+
    '<div class="label">'+m.label+'</div>'+
    '<div class="val'+(hasVal?'':' none')+'">'+valStr+'</div>'+
    '<div class="n">'+m.count+' labeled</div>'+
    flag+
    '</div>';
}

function renderCurve(curve){
  const el=document.getElementById("curve");
  if(!curve.length){ el.innerHTML='<div class="empty">No confidence-scored outcomes yet.</div>'; return; }
  el.innerHTML=curve.map(c=>
    '<div class="curve-row">'+
      '<div class="curve-band">'+c.band+'</div>'+
      '<div class="curve-track">'+
        '<div class="curve-observed" style="width:'+(c.observed*100)+'%"></div>'+
        '<div class="curve-claimed" style="left:'+(c.claimed*100)+'%"></div>'+
      '</div>'+
      '<div class="curve-meta">obs '+(c.observed*100).toFixed(0)+'% · n='+c.count+'</div>'+
    '</div>'
  ).join("");
}

async function load(){
  const d=await fetch("/api/calibration/metrics").then(x=>x.json());
  const total=d.total_labeled;
  const need=d.min_stable_samples;
  const b=document.getElementById("banner");
  if(total < need){
    b.innerHTML='<b>'+total+' prediction'+(total===1?'':'s')+' labeled.</b> '+
      'Metrics below are computed but <b>not yet statistically stable</b> — '+
      'calibration needs ~'+need+' labeled outcomes per type to be reliable. '+
      'The engine is live and will sharpen automatically as prediction horizons mature and you label outcomes.';
  } else {
    b.innerHTML='<b>'+total+' predictions labeled.</b> Metrics are statistically stable.';
  }
  const grid=document.getElementById("metricGrid");
  const m=d.metrics;
  grid.innerHTML=
    metricCard("sev",m.severity_mae)+
    metricCard("dur",m.duration_mae)+
    metricCard("scn",m.scenario_brier)+
    metricCard("ind",m.industry_accuracy);
  renderCurve(d.calibration_curve);
}
load();
</script>
</body>
</html>
"""
