/* No fabricated samples: all charts render the collector's API response. */
const $ = id => document.getElementById(id);
let current = null, posting = false;
const fmt = (value, digits = 1) => Number.isFinite(value) ? value.toLocaleString('fr-FR', {maximumFractionDigits: digits, minimumFractionDigits: digits}) : '—';
const clock = iso => new Date(iso).toISOString().slice(11, 19);
function message(text) { $('toast').textContent = text; $('toast').hidden = false; setTimeout(() => $('toast').hidden = true, 5000); }
function chart(id, series, {threshold = null, minimum = 1, empty = 'En attente de mesures…'} = {}) {
  const canvas = $(id), w = canvas.clientWidth, h = Number(canvas.getAttribute('height'));
  if (!w) return;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); canvas.style.height = h + 'px';
  // Store logical height because canvas.height now contains physical pixels.
  canvas.setAttribute('height', String(h)); canvas.height = Math.round(h * dpr);
  canvas.dataset.logicalHeight = h;
  const ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
  const left = 43, right = w - 12, top = 12, bottom = h - 23;
  const values = series.flatMap(s => s.values).filter(Number.isFinite);
  const max = Math.max(minimum, threshold ? threshold * 1.3 : 0, ...values) * 1.12;
  ctx.font = '10px Consolas, monospace'; ctx.textBaseline = 'middle';
  for (let i = 0; i <= 3; i++) {
    const y = top + (bottom - top) * i / 3;
    ctx.strokeStyle = '#e9eeeb'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
    ctx.fillStyle = '#84938f'; ctx.fillText(fmt(max * (1 - i / 3), max > 10 ? 0 : 1), 0, y);
  }
  if (!values.length) { ctx.fillStyle = '#84938f'; ctx.textAlign = 'center'; ctx.fillText(empty, w / 2, h / 2); return; }
  if (threshold !== null) {
    const y = bottom - threshold / max * (bottom - top);
    ctx.strokeStyle = '#c75243'; ctx.setLineDash([4, 5]); ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = '#c75243'; ctx.fillText('SEUIL', right - 38, Math.max(8, y - 8));
  }
  for (const s of series) {
    ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.beginPath(); let drawing = false;
    s.values.forEach((value, i) => {
      if (!Number.isFinite(value)) { drawing = false; return; }
      const x = left + i / Math.max(1, s.values.length - 1) * (right - left), y = bottom - value / max * (bottom - top);
      if (!drawing) ctx.moveTo(x, y); else ctx.lineTo(x, y); drawing = true;
    }); ctx.stroke();
  }
  ctx.fillStyle = '#84938f'; ctx.fillText('DÉBUT', left, h - 5); ctx.textAlign = 'right'; ctx.fillText('MAINTENANT', right, h - 5);
}
// Canvas dimensions must stay stable across redraws at high-DPI resolutions.
const heights = {trafficChart:185, scoreChart:155, lossChart:180};
function draw(id, series, options) { $(id).setAttribute('height', String(heights[id])); chart(id, series, options); }
function render(s) {
  current = s; const p = s.latest, m = s.model, busy = ['collecting','training'].includes(s.phase), ready = s.phase === 'ready';
  document.body.classList.remove('offline'); document.body.classList.toggle('alerting', !!p?.alert);
  $('connection').textContent = 'EN DIRECT';
  const states = {untrained:['Modèle à entraîner','Commencez par la calibration du trafic normal.'],collecting:['Collecte du trafic normal','Les mesures réelles construisent le jeu d’apprentissage.'],training:['Apprentissage en cours','Optimisation des poids du réseau avec PyTorch.'],error:['Entraînement interrompu','Consultez le message ci-dessous.'],ready: p?.alert ? ['Anomalie détectée','Deux fenêtres successives au-dessus du seuil.'] : p?.candidate ? ['Fenêtre suspecte','En attente d’une deuxième fenêtre pour confirmer.'] : !p?.rps ? ['Surveillance en attente','Aucune requête terminée dans cette fenêtre.'] : ['Trafic dans la référence apprise','Score de reconstruction inférieur au seuil.']};
  const status = states[s.phase] || states.untrained;
  $('statusText').textContent = status[0]; $('statusDetail').textContent = status[1];
  $('lastUpdate').textContent = p ? clock(p.timestamp) + ' UTC' : '—';
  $('rps').textContent = fmt(p?.rps); $('latency').textContent = fmt(p?.p95_ms, 0); $('errors').textContent = fmt(p ? p.error_rate * 100 : null); $('score').textContent = fmt(p?.ratio, 2);
  $('total').textContent = `${s.total_requests.toLocaleString('fr-FR')} requêtes observées`;
  $('progressText').textContent = s.phase === 'collecting' ? 'Collecte normale en cours' : s.phase === 'training' ? 'Apprentissage des poids…' : m ? 'Modèle entraîné et sauvegardé' : 'En attente de calibration';
  $('progressCount').textContent = busy ? `${s.calibration_count} / ${s.calibration_target}` : m ? `${m.normal_windows} fenêtres` : '0 / 90';
  $('progressBar').style.width = (busy ? s.calibration_count / s.calibration_target * 100 : m ? 100 : 0) + '%';
  $('calibrateBtn').disabled = busy || posting || s.scenario !== 'normal';
  $('attackBtn').disabled = !ready || posting || s.scenario !== 'normal'; $('legitimateBtn').disabled = !ready || posting || s.scenario !== 'normal'; $('normalBtn').disabled = busy || posting;
  $('scenarioText').textContent = s.scenario === 'attack' ? `Surcharge · ${s.scenario_remaining} s restantes` : s.scenario === 'legitimate' ? `Pic légitime · ${s.scenario_remaining} s restantes` : s.normal ? 'Trafic normal' : 'Trafic arrêté';
  $('scenarioDetail').textContent = s.scenario === 'attack' ? 'Consigne de 100 req/s · API locale' : s.scenario === 'legitimate' ? '24 req/s · charge normale plus soutenue' : '8 à 24 requêtes/s · cible fixe locale';
  $('countdown').style.width = s.scenario === 'normal' ? '0' : (s.scenario_remaining / 25 * 100) + '%';
  $('delay').textContent = s.detection_seconds === null ? '—' : fmt(s.detection_seconds, 2) + ' s';
  $('errorBox').hidden = !s.error; $('errorBox').textContent = s.error || '';
  draw('trafficChart',[{values:s.history.map(x=>x.rps),color:'#137f75'}],{minimum:30});
  draw('scoreChart',[{values:s.history.map(x=>x.ratio),color:'#7662ac'}],{threshold:1,minimum:2,empty:'Calibrez le réseau pour obtenir ses premiers scores.'});
  $('contributions').replaceChildren();
  if (p?.contributions?.length) {
    const label=document.createElement('span'); label.textContent='Contributions à l’erreur :'; $('contributions').append(label);
    p.contributions.slice(0,3).forEach(c=>{const chip=document.createElement('span');chip.className='chip';chip.textContent=`${c.name} · ${fmt(c.share*100,0)} %`;$('contributions').append(chip);});
  } else $('contributions').textContent='Les contributions au score apparaîtront après calibration.';
  $('parameters').textContent=m?.parameters ?? '—'; $('trainWindows').textContent=m?.train_windows ?? '—'; $('valWindows').textContent=m?.validation_windows ?? '—';
  $('modelBadge').textContent=m ? `PyTorch · ${m.epochs} époques` : 'À entraîner';
  draw('lossChart',[{values:m?.history.map(x=>x.train)||[],color:'#137f75'},{values:m?.history.map(x=>x.validation)||[],color:'#7662ac'}],{minimum:.1,empty:'La courbe apparaîtra après entraînement.'});
  $('trainingNote').textContent=m ? `Meilleure époque : ${m.best_epoch}. Seuil : ${fmt(m.threshold,3)}. Validation chronologique normale ; ces valeurs ne sont pas des taux de détection.` : 'Le modèle sera entraîné uniquement sur les fenêtres normales collectées ici.';
  $('requestRows').replaceChildren(); s.requests.slice(0,8).forEach(r=>{const tr=document.createElement('tr');[clock(r.time),'/api/service',String(r.status),fmt(r.latency,0)+' ms'].forEach((v,i)=>{const td=document.createElement('td');td.textContent=v;if(i===2)td.className=r.status===200?'http-ok':'http-error';tr.append(td);});$('requestRows').append(tr);});
  $('eventList').replaceChildren();s.events.forEach(e=>{const row=document.createElement('div');row.className='event '+e.kind;const time=document.createElement('time');time.textContent=clock(e.time);const marker=document.createElement('span');marker.className='event-marker';const text=document.createElement('span');text.className='event-message';text.textContent=e.message;row.append(time,marker,text);$('eventList').append(row);});
}
async function command(action) {
  if(posting || !current)return;posting=true;render(current);
  try {const response=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':current.token},body:JSON.stringify({action})});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Commande refusée.');message(action==='attack'?'Surcharge locale lancée pour 25 secondes.':action==='calibrate'?'Collecte normale lancée. Gardez le laboratoire ouvert.':action==='stop'?'Trafic arrêté.':'Scénario activé.');}
  catch(e){message(e.message);}finally{posting=false;}
}
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>command(b.dataset.action)));
[6,12,6,2,6,12,6].forEach((n,i)=>{if(i){const arrow=document.createElement('span');arrow.className='layer-arrow';arrow.textContent='→';$('architecture').append(arrow);}const layer=document.createElement('span');layer.className='layer'+(i===3?' mid':'');layer.textContent=n;$('architecture').append(layer);});
async function poll(){try{const r=await fetch('/api/state',{signal:AbortSignal.timeout(5000)});if(!r.ok)throw new Error();render(await r.json());}catch{document.body.classList.add('offline');$('connection').textContent='DÉCONNECTÉ';$('statusText').textContent='Connexion au laboratoire perdue';$('statusDetail').textContent='Vérifiez que le lanceur est toujours ouvert. Les courbes affichées sont les dernières mesures reçues.';}finally{setTimeout(poll,1000);}}
window.addEventListener('resize',()=>{if(current)render(current);});poll();
