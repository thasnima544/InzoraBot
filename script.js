// ---------- helpers ----------
const $ = (id) => document.getElementById(id);
const safeEl = (id) => document.getElementById(id) || { textContent:'', style:{} };
const asNum = (x, d='--') => (x===undefined||x===null || Number.isNaN(x)) ? d : x;

// ---------- top clock ----------
function fmtClock(){
  const d = new Date();
  const pad = (n)=> String(n).padStart(2,'0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
(function tickClock(){
  const el = $("clock"); if (el) el.textContent = fmtClock() + " GMT+0";
  requestAnimationFrame(tickClock);
})();

// ---------- net strength ----------
function setBars(q){
  const bars = [ $("b1"), $("b2"), $("b3"), $("b4") ].filter(Boolean);
  const levels = Math.round(((+q||0)/100)*4);
  bars.forEach((b,i)=> b.classList.toggle("on", i < levels));
}
const sparkPoints = [];
function drawSpark(v){
  const c = $("spark"); if (!c) return;
  const ctx = c.getContext("2d");
  sparkPoints.push(+v||0);
  if (sparkPoints.length > 80) sparkPoints.shift();
  ctx.clearRect(0,0,c.width,c.height);
  ctx.strokeStyle = "#33e1a1"; ctx.lineWidth = 2; ctx.beginPath();
  sparkPoints.forEach((y,i)=>{
    const x = (i/(80-1))* (c.width-8) + 4;
    const ya = c.height - (y/100)*(c.height-8) - 4;
    if(i===0) ctx.moveTo(x, ya); else ctx.lineTo(x, ya);
  });
  ctx.stroke();
}

// ---------- logging ----------
function logLine(t){
  const el = $("log"); if (!el) return;
  const time = new Date().toLocaleTimeString();
  el.innerHTML = `<div>[${time}] ${t}</div>` + el.innerHTML;
}

// ---------- comms chip ----------
let COMMS_ENABLED = true;
function setComms(enabled){
  COMMS_ENABLED = !!enabled;
  const chip = $("comms-chip");
  if (!chip) return;
  if (COMMS_ENABLED){
    chip.classList.remove("off");
    chip.innerHTML = `<span class="chip-dot"></span> Two-Way Comms: Enabled`;
  } else {
    chip.classList.add("off");
    chip.innerHTML = `<span class="chip-dot"></span> Two-Way Comms: Disabled`;
  }
}
// call once at load
setComms(true);

// ---------- comms modals ----------
function openModal(kind){ const m = document.getElementById(`modal-${kind}`); if (m) m.classList.add('show'); }
function closeModal(kind){ const m = document.getElementById(`modal-${kind}`); if (m) m.classList.remove('show'); }
window.openModal = openModal; window.closeModal = closeModal;

// ---------- bot control via Flask proxy ----------
async function sendCmd(cmd){
  logLine(`CTRL • ${cmd}`);
  try{
    const r = await fetch("/control",{
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ cmd })
    });
    const j = await r.json();
    if(!j.ok) logLine(`CTRL ERR • ${j.error||j.status}`);
  }catch(e){ logLine(`CTRL NET ERR • ${e}`); }
}
window.sendCmd = sendCmd;

// Keyboard control
document.addEventListener('keydown', (ev)=>{
  const k = ev.key.toLowerCase();
  if      (k==='w' || k==='arrowup')    sendCmd('F');
  else if (k==='s' || k==='arrowdown')  sendCmd('B');
  else if (k==='a' || k==='arrowleft')  sendCmd('L');
  else if (k==='d' || k==='arrowright') sendCmd('R');
  else if (k===' ') { ev.preventDefault(); sendCmd('S'); }
  else if (k==='q') sendCmd('SLOW');
  else if (k==='e') sendCmd('FAST');
});

// ---------- prediction ----------
function rescuerRecommendation(survivors){
  const n = Math.max(0, +survivors || 0);
  if (n <= 2) return 2;
  if (n <= 4) return 4;
  if (n <= 6) return 6;
  return Math.ceil(n * 1.2);
}
function applyPrediction(n){
  const ppl = Math.max(0, Math.floor(+n || 0));
  safeEl("ppl").textContent = ppl;
  safeEl("resc").textContent = rescuerRecommendation(ppl);
}
// Manual override
(function bindOverride(){
  const input = $("survivor-input");
  const btn = $("apply-override");
  if (!input || !btn) return;
  btn.addEventListener("click", ()=>{
    applyPrediction(input.value);
    logLine(`PRED • manual survivors=${input.value}`);
  });
})();

// ---------- MAP (Google with Leaflet fallback) & ZONES ----------
let mapMode = 'leaflet'; // 'gmap' or 'leaflet'
let map, botMarker, pathLine, optimizeMode = false, targetLatLng = null;
const trail = [];

// Dynamic danger circle around bot (based on live sensors)
let dangerCircle = null;

// Optional: demo sector polygons (static) to visualize zone colors quickly
const DEMO_SECTORS = [
  // rectangles defined by SW and NE corners
  { sw:{lat:11.3125, lng:77.5490}, ne:{lat:11.3162, lng:77.5522}, level:'yellow' },
  { sw:{lat:11.3140, lng:77.5550}, ne:{lat:11.3172, lng:77.5592}, level:'orange' },
];

// Level → colors
const LEVEL_STYLE = {
  green:  { stroke: '#2aa84a', fill: 'rgba(42,168,74,0.22)' },
  yellow: { stroke: '#e6b800', fill: 'rgba(230,184,0,0.22)' },
  orange: { stroke: '#ff7a00', fill: 'rgba(255,122,0,0.22)' },
  red:    { stroke: '#e33a3a', fill: 'rgba(227,58,58,0.25)' },
};

// decide level from sensors
function levelFromSensors(d){
  const gas = +d.gas || 0;
  const vib = +d.vibration || 0;
  const press = +d.pressure || 0;

  if (gas > 800 || vib > 3.0) return 'red';
  if (gas > 500 || vib > 2.0) return 'orange';
  if (gas > 250 || vib > 1.0) return 'yellow';
  return 'green';
}

function setOptimizeMode(v){
  optimizeMode = v;
  logLine(v? "MAP • Click to set target":"MAP • Optimize off");
}
window.setOptimizeMode = setOptimizeMode;

function clearTrail(){
  trail.length = 0;
  if (mapMode === 'leaflet' && pathLine) pathLine.setLatLngs([]);
  if (mapMode === 'gmap' && pathLine)    pathLine.setPath([]);
}
window.clearTrail = clearTrail;

// --- Leaflet path & zones ---
function drawLeafletDemoSectors(){
  DEMO_SECTORS.forEach(s=>{
    const bounds = [[s.sw.lat, s.sw.lng],[s.ne.lat, s.ne.lng]];
    const st = LEVEL_STYLE[s.level];
    L.rectangle(bounds, { color: st.stroke, weight: 2, fillColor: st.fill, fillOpacity: 0.6 }).addTo(map);
  });
}

function setLeafletDangerCircle(lat, lng, level){
  const st = LEVEL_STYLE[level];
  if (dangerCircle) dangerCircle.remove();
  dangerCircle = L.circle([lat, lng], {
    radius: 150, // meters
    color: st.stroke, weight: 2, fillColor: st.fill, fillOpacity: 0.6
  }).addTo(map);
}

function initLeaflet(){
  const start = [11.313992, 77.553115];
  map = L.map("map",{ zoomControl:true }).setView(start, 15);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { attribution:"© OpenStreetMap contributors" }).addTo(map);

  botMarker = L.marker(start).addTo(map).bindPopup("Rescue BOT");
  pathLine = L.polyline([], { color:"#10b9ff", weight:3 }).addTo(map);

  // demo zones
  drawLeafletDemoSectors();

  map.on("click", (e)=>{
    if(!optimizeMode) return;
    targetLatLng = e.latlng;
    L.marker(targetLatLng, {opacity:0.8}).addTo(map).bindPopup("Target").openPopup();
    drawOptimizedPath();
    setOptimizeMode(false);
  });

  mapMode = 'leaflet';
  logLine("ℹ Leaflet map loaded (fallback)");
}

// --- Google path & zones ---
let gDemoRects = [];
function drawGoogleDemoSectors(){
  // Clean existing
  gDemoRects.forEach(r=> r.setMap(null));
  gDemoRects = [];

  DEMO_SECTORS.forEach(s=>{
    const st = LEVEL_STYLE[s.level];
    const rect = new google.maps.Rectangle({
      map,
      bounds: { south: s.sw.lat, west: s.sw.lng, north: s.ne.lat, east: s.ne.lng },
      strokeColor: st.stroke, strokeWeight: 2, strokeOpacity: 1.0,
      fillColor: st.stroke, fillOpacity: 0.18
    });
    gDemoRects.push(rect);
  });
}

let gDangerCircle = null;
function setGoogleDangerCircle(lat, lng, level){
  const st = LEVEL_STYLE[level];
  if (gDangerCircle) gDangerCircle.setMap(null);
  gDangerCircle = new google.maps.Circle({
    map,
    center: {lat, lng},
    radius: 150,
    strokeColor: st.stroke, strokeWeight: 2, strokeOpacity: 1.0,
    fillColor: st.stroke, fillOpacity: 0.22
  });
}

function initMap(){
  const mapDiv = $("map");
  if (!mapDiv) return;

  if (window.google && google.maps) {
    const start = { lat: 11.313992, lng: 77.553115 };
    map = new google.maps.Map(mapDiv, { center: start, zoom: 15, mapTypeId: "roadmap" });
    botMarker = new google.maps.Marker({ position: start, map });

    pathLine = new google.maps.Polyline({
      path: [],
      geodesic: true,
      strokeColor: "#10b9ff",
      strokeOpacity: 1.0,
      strokeWeight: 3,
      map
    });

    // demo zones
    drawGoogleDemoSectors();

    map.addListener("click", (e)=>{
      if(!optimizeMode) return;
      targetLatLng = e.latLng;
      new google.maps.Marker({ position: targetLatLng, map, opacity: 0.9, title:"Target" });
      drawOptimizedPath();
      setOptimizeMode(false);
    });

    mapMode = 'gmap';
    logLine("✅ Google Map loaded");
  } else {
    initLeaflet();
  }
}
window.initMap = initMap; // required for Google callback

function drawOptimizedPath(){
  if(!targetLatLng || trail.length === 0) return;

  if (mapMode === 'leaflet') {
    const last = trail[trail.length-1];
    const line = [ [last.lat, last.lng], [targetLatLng.lat, targetLatLng.lng] ];
    L.polyline(line, { color:"#33e1a1", dashArray:"6 6", weight:3 }).addTo(map);
    const dist = map.distance([last.lat,last.lng],[targetLatLng.lat,targetLatLng.lng]); // m
    const etaMin = (dist/1.2)/60; // ~1.2 m/s
    safeEl("eta").textContent = `${etaMin.toFixed(1)} min`;
  } else {
    const last = trail[trail.length-1];
    const from = new google.maps.LatLng(last.lat, last.lng);
    const to   = targetLatLng;
    new google.maps.Polyline({
      path: [from, to],
      geodesic: true,
      strokeColor: "#33e1a1",
      strokeOpacity: 1.0,
      strokeWeight: 3,
      map
    });
    const dist = google.maps.geometry?.spherical?.computeDistanceBetween
      ? google.maps.geometry.spherical.computeDistanceBetween(from, to)
      : 0;
    const etaMin = (dist/1.2)/60;
    safeEl("eta").textContent = isFinite(etaMin) ? `${etaMin.toFixed(1)} min` : '—';
  }
}

function updateMapPosition(lat, lon){
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

  if (mapMode === 'leaflet') {
    botMarker.setLatLng([lat, lon]);
    trail.push({lat, lng: lon});
    if (trail.length > 1) pathLine.setLatLngs(trail.map(p => [p.lat, p.lng]));
    if (trail.length === 1) map.setView([lat, lon], 16);
  } else {
    const pos = new google.maps.LatLng(lat, lon);
    botMarker.setPosition(pos);
    const path = pathLine.getPath();
    path.push(pos);
    trail.push({lat, lng: lon});
    if (trail.length === 1) map.setCenter(pos);
  }
}

// set/update a colored danger circle at bot position
function paintDangerZone(lat, lon, level){
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
  if (mapMode === 'leaflet') {
    setLeafletDangerCircle(lat, lon, level);
  } else {
    setGoogleDangerCircle(lat, lon, level);
  }
}

// ---------- sensors (live + fallback) ----------
async function latestOrHistory(){
  let d = await fetch("/sensor_data").then(r=>r.json()).catch(()=>({error:'fetch'}));
  if (d.stale || d.error){
    const hist = await fetch("/sensor_history?n=1").then(r=>r.json()).catch(()=>[]);
    if (Array.isArray(hist) && hist.length) d = hist[0];
  }
  return d || {};
}

async function pullSensors(){
  try{
    const d = await latestOrHistory();

    // Telemetry
    safeEl("t-temp").textContent  = `${asNum(+d.temp)} °C`;
    safeEl("t-gas").textContent   = `${asNum(+d.gas)} ppm`;
    safeEl("t-press").textContent = `${asNum(+d.pressure)} hPa`;
    safeEl("t-vib").textContent   = `${asNum(+d.vibration)} g`;

    const lat = Number(d.latitude), lon = Number(d.longitude);
    safeEl("t-gps").textContent = (Number.isFinite(lat) && Number.isFinite(lon))
      ? `${lat.toFixed(6)} , ${lon.toFixed(6)}`
      : "-- , --";

    const batt = Math.max(0, Math.min(100, Number(d.battery ?? 80)));
    const battBar = safeEl("bot-batt"); if (battBar.style) battBar.style.width = `${batt}%`;
    safeEl("bot-batt-text").textContent = `${batt}%`;
    safeEl("bot-mode").textContent = d.mode ?? "—";

    // Prediction from survivors
    const survivors = Number(d.survivors ?? d.people ?? 0);
    applyPrediction(survivors);

    // Map path and emergency zone
    if (Number.isFinite(lat) && Number.isFinite(lon) && (window.map)) {
      updateMapPosition(lat, lon);
      const lvl = levelFromSensors(d);
      paintDangerZone(lat, lon, lvl);
    }

    // Example: flip comms chip off if quality is very low
    if (typeof d.quality === 'number' && d.quality < 10) setComms(false);
    else setComms(true);

  }catch(e){ /* ignore */ }
}

async function pullNetwork(){
  try{
    const d = await fetch("/network").then(r=>r.json());
    safeEl("rssi").textContent = d.rssi ?? "--";
    safeEl("qual").textContent = d.quality ?? "--";
    setBars(d.quality ?? 0);
    drawSpark(d.quality ?? 0);
    logLine(`NET • RSSI ${d.rssi} dBm • Q ${d.quality}%`);

    // === Communications Dock synthesis (simple, realistic mapping) ===
    const q = Math.max(0, Math.min(100, Number(d.quality || 0)));

    // Data Link (Mbps, Latency, Loss)
    const ul = (q * 0.06).toFixed(2);      // 0–6 Mbps
    const dl = (q * 0.08).toFixed(2);      // 0–8 Mbps
    const lat = Math.round(250 - q*2);     // 250→50 ms
    const loss = Math.max(0, (30 - q*0.25)).toFixed(1); // 30%→5%

    safeEl("ul-data").textContent = `${ul} Mbps`;
    safeEl("dl-data").textContent = `${dl} Mbps`;
    safeEl("lat-data").textContent = `${lat} ms`;
    safeEl("loss-data").textContent = `${loss} %`;

    // Voice (kbps, jitter)
    const brv = Math.max(12, Math.round(12 + q*0.8));  // ~12–92 kbps
    const jit = Math.max(2, Math.round(18 - q*0.15));  // ~18→3 ms
    safeEl("br-voice").textContent = `${brv}`;
    safeEl("lat-voice").textContent = `${Math.round(lat*0.6)} ms`;
    safeEl("jit-voice").textContent = `${jit} ms`;

    // Video (Mbps/FPS/Res)
    const br = (q * 0.05).toFixed(2);      // 0–5 Mbps
    const fps = Math.max(5, Math.round(q/4)); // 5–25
    const res = q > 70 ? "1280×720" : q > 40 ? "854×480" : "640×360";
    safeEl("br-video").textContent = `${br} Mbps`;
    safeEl("fps-video").textContent = `${fps}`;
    safeEl("res-video").textContent = res;
    safeEl("lat-video").textContent = `${Math.round(lat*0.8)} ms`;

    // Chat
    safeEl("del-chat").textContent = Math.round(3 + q/5); // msgs/min estimate
    safeEl("ack-chat").textContent = `${Math.round(lat*0.5)} ms`;
    safeEl("st-chat").textContent = q < 10 ? "Degraded" : "OK";

    // Global comms chip + card states
    const chip = $("comms-chip-main");
    const mainState = $("comms-link-state");
    const on = q >= 10;
    if (on){
      chip.classList.remove("off");
      if (mainState) mainState.textContent = "Enabled";
    } else {
      chip.classList.add("off");
      if (mainState) mainState.textContent = "Disabled";
    }
    ["data","voice","video","chat"].forEach(key=>{
      const el = $(`state-${key}`);
      if (!el) return;
      el.classList.toggle('off', !on);
      el.classList.toggle('on', on);
      el.textContent = on ? "ON" : "OFF";
    });

  }catch(e){
    // on failure, show disabled state
    const chip = $("comms-chip-main");
    if (chip) chip.classList.add("off");
    ["data","voice","video","chat"].forEach(key=>{
      const el = $(`state-${key}`);
      if (el){ el.classList.remove('on'); el.classList.add('off'); el.textContent = "OFF"; }
    });
  }
}
