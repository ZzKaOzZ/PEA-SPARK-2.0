
const D = {
  conductors:[], switches:[], reclosers:[], transformers:[], substations:[],
  feeders:[], scada:null, outagePoly:null,
  faultMapClickSnapM:200, faultCoordSnapM:20,
  fault:{active:false,feeder:null,feeders:[],lat:null,lon:null},
  maint:{active:false,feeder:null,startLat:null,startLon:null,endLat:null,endLon:null,jobName:null,jobNumber:null},
  feederFilter:null, swClassFilter:null, selectedSwitch:null, armMode:false, maintMode:false,
  layers:{switches:true,dropouts:false,reclosers:true,transformers:false,substations:true,outage:true},
  plan:null, planDone:0, planNormDone:0,
  mapBusy:false,           // R3: true while zooming/panning
  pendingRefresh:false,    // R3: coalesce refreshes during interaction
  refreshBusy:false,       // R51: block overlapping live-refresh storms
  mapGen:0,                // R74: drop stale /live-refresh that loses to execute
};

const map = L.map("map",{zoomControl:true,preferCanvas:true}).setView([11.81,99.79],12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
  {attribution:"© OpenStreetMap contributors",maxZoom:19}).addTo(map);

// R3: track when the user is interacting with the map so we don't redraw mid-zoom
map.on("zoomstart movestart",()=>{D.mapBusy=true;});
map.on("zoomend moveend",()=>{
  D.mapBusy=false;
  if(D.pendingRefresh){D.pendingRefresh=false;refreshLive();}
});

const lyr = {
  // Outage under network so restored PDA05 tint stays visible at ties (R76).
  outage:      L.layerGroup().addTo(map),
  conductors:  L.layerGroup().addTo(map),
  switches:    L.layerGroup().addTo(map),
  dropouts:    L.layerGroup(),
  reclosers:   L.layerGroup().addTo(map),
  transformers:L.layerGroup(),
  substations: L.layerGroup().addTo(map),
  fault:       L.layerGroup().addTo(map),
  maint:       L.layerGroup().addTo(map),
};

function ensureMapLayerOrder(){
  lyr.outage.bringToBack();
  lyr.conductors.bringToFront();
  if(map.hasLayer(lyr.dropouts)) lyr.dropouts.bringToFront();
  if(map.hasLayer(lyr.transformers)) lyr.transformers.bringToFront();
  lyr.switches.bringToFront();
  lyr.reclosers.bringToFront();
  lyr.substations.bringToFront();
  lyr.maint.bringToFront();
  lyr.fault.bringToFront();
}

const j = url => fetch(url).then(async r=>{
  if(!r.ok) throw new Error(`${url} HTTP ${r.status}`);
  return r.json();
});
const post = (url,body={}) => fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}).then(async r=>{
  const data=await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(data.error||`${url} HTTP ${r.status}`);
  return data;
});

function setMapProcessing(on,msg){
  const el=document.getElementById("map-processing");
  const txt=document.getElementById("map-processing-text");
  if(!el) return;
  if(on){
    el.classList.add("visible");
    if(msg&&txt) txt.textContent=msg;
  }else{
    el.classList.remove("visible");
  }
}

function fillCauseOptions(causes){
  const sel=document.getElementById("ff-cause");
  if(!sel||!causes?.length) return;
  sel.innerHTML=causes.map(c=>`<option>${c}</option>`).join("");
}

async function loadAll(){
  const banner=document.getElementById("fault-banner");
  if(banner){banner.style.display="block";banner.textContent="⏳ กำลังโหลดเครือข่าย… (ครั้งแรกอาจใช้เวลา 1–2 นาที)";}
  setMapProcessing(true,"กำลังโหลดเครือข่าย…");
  try{
    const [bundle,xf,fd,fc,nc] = await Promise.all([
      j("/live-refresh"),j("/transformers"),j("/feeders"),
      j("/api/fault-causes"),j("/api/network-config"),
    ]);
    fillCauseOptions(fc.causes);
    if(nc?.faultMapClickSnapM) D.faultMapClickSnapM=nc.faultMapClickSnapM;
    if(nc?.faultCoordSnapM) D.faultCoordSnapM=nc.faultCoordSnapM;
    applyLiveBundle(bundle);
    D.transformers=xf.features;
    D.feeders=fd.feeders;
    const sc=bundle.scada;
    if(sc.faultActive){
      D.fault={active:true,feeder:sc.faultFeeder,feeders:sc.faultFeeders||[sc.faultFeeder].filter(Boolean),
               lat:sc.faultLat??null,lon:sc.faultLon??null};
    }
    if(sc.maintActive){
      D.maint={active:true,feeder:sc.maintFeeder,
        startLat:sc.maintStartLat,startLon:sc.maintStartLon,
        endLat:sc.maintEndLat,endLon:sc.maintEndLon,
        jobName:sc.maintJobName,jobNumber:sc.maintJobNumber};
    }
    renderFeeders();
    renderAll(); fitBounds(); drawFault(); drawMaintenance();
    if(banner&&!D.fault.active&&!D.maint.active) banner.style.display="none";
  }catch(err){
    console.error("loadAll failed:",err);
    if(banner){
      banner.style.display="block";
      banner.textContent="❌ โหลดข้อมูลไม่สำเร็จ — รีสตาร์ท python app.py แล้วกด Ctrl+F5";
    }
  }finally{
    setMapProcessing(false);
  }
}

function applyLiveBundle(bundle){
  applyLivePayload({
    conductors:bundle.conductors,
    switches:bundle.switches,
    reclosers:bundle.reclosers,
    substations:bundle.substations,
    scada:bundle.scada,
    outagePoly:bundle.outagePoly,
  });
}

function applyLivePayload(sc){
  if(!sc?.scada) return;
  if(sc.conductors?.features) D.conductors=sc.conductors.features;
  if(sc.switches?.features) D.switches=sc.switches.features;
  if(sc.reclosers?.features) D.reclosers=sc.reclosers.features;
  if(sc.substations?.features) D.substations=sc.substations.features;
  D.scada=sc.scada;
  if(sc.outagePoly) D.outagePoly=sc.outagePoly;
  // R5: keep fault marker coords in sync with server
  if(sc.scada.faultActive && (D.fault.lat==null||D.fault.lon==null)){
    D.fault={active:true,feeder:sc.scada.faultFeeder,feeders:sc.scada.faultFeeders||[sc.scada.faultFeeder].filter(Boolean),
      lat:sc.scada.faultLat,lon:sc.scada.faultLon};
    drawFault();
  }
  if(!sc.scada.faultActive && D.fault.active){
    D.fault={active:false,feeder:null,feeders:[],lat:null,lon:null};
    D.outagePoly={type:"FeatureCollection",features:[]};
    drawFault();
  }
  if(sc.scada.maintActive){
    D.maint={active:true,feeder:sc.scada.maintFeeder,
      startLat:sc.scada.maintStartLat,startLon:sc.scada.maintStartLon,
      endLat:sc.scada.maintEndLat,endLon:sc.scada.maintEndLon,
      jobName:sc.scada.maintJobName,jobNumber:sc.scada.maintJobNumber};
    drawMaintenance();
  }
  if(!sc.scada.maintActive && D.maint.active){
    D.maint={active:false,feeder:null,startLat:null,startLon:null,endLat:null,endLon:null,jobName:null,jobNumber:null};
    if(!sc.scada.faultActive) D.outagePoly={type:"FeatureCollection",features:[]};
    drawMaintenance();
  }
  drawOutage(); drawConductors(); drawSwitches(); drawReclosers(); drawSubstations(); drawMaintenance();
  ensureMapLayerOrder();
  updateHeader(); renderStatus(); renderSwitches();
  const banner=document.getElementById("fault-banner");
  if(banner && sc.scada.faultActive){
    banner.textContent=sc.scada.lineDisplayPhysical
      ? "⚡ Real-time — สีสาย=ฟีดเดอร์ต้นทางจ่ายจริง · ดูแถบ Status ว่าใช้ฟีดเดอร์ไหนอยู่"
      : sc.scada.lineDisplayIsolation
      ? "🔧 แยกวงจรแล้ว — กดยืนยันปลายสาย (ขั้น NOTE) เพื่อแสดงไฟย้อนจาก KUA01"
      : "⚠ กรอกพิกัดจากหน้างาน (ห่างจากสายไม่เกิน 20 m) · เลือกฟีดเดอร์ถ้ามีหลายสาย · สาเหตุ/เฟส · คลิกแผนที่หรือกดตั้งจากพิกัด";
  }
}

async function refreshLive(opts={}){
  const force=opts.force===true;
  if(!force&&D.mapBusy){D.pendingRefresh=true;return;}
  // R74: force may still queue behind an in-flight poll — never drop the update.
  if(D.refreshBusy){D.pendingRefresh=true;return;}
  D.refreshBusy=true;
  const gen=D.mapGen;
  setMapProcessing(true,"กำลังอัปเดตแผนที่…");
  try{
    const bundle=await j("/live-refresh");
    // Stale poll started before execute liveMap — do not overwrite PDA05 tint.
    if(gen!==D.mapGen) return;
    applyLiveBundle(bundle);
  }catch(err){
    console.error("refreshLive failed:",err);
  }finally{
    D.refreshBusy=false;
    setMapProcessing(false);
    if(D.pendingRefresh&&!D.mapBusy){
      D.pendingRefresh=false;
      setTimeout(()=>refreshLive({force:true}),250);
    }
  }
  scheduleRefreshLive();
}

/** After switching-plan execute — same single-pass refresh (R51/R53). */
async function refreshLiveAfterPlanStep(){
  await refreshLive({force:true});
}

const refreshAll = ()=>loadAll();

function renderAll(){
  // Outage under conductors so restored PDA05 tint stays visible (R76).
  drawOutage(); drawConductors(); drawSwitches(); drawReclosers(); drawTransformers();
  drawSubstations(); drawFault(); drawMaintenance();
  ensureMapLayerOrder();
  updateHeader(); renderSwitches(); renderFeeders(); renderStatus();
}

const di=(html,sz,anc)=>L.divIcon({className:"",html,iconSize:sz,iconAnchor:anc||[sz[0]/2,sz[1]/2]});

function drawConductors(){
  lyr.conductors.clearLayers();
  const ff=D.feederFilter;
  const sorted=[...D.conductors].sort((a,b)=>(a.properties.status==="off"?1:0)-(b.properties.status==="off"?1:0));
  for(const f of sorted){
    if(ff && f.properties.feeder!==ff) continue;
    const p=f.properties;
    const off=p.status==="off";
    const pts=f.geometry.coordinates.map(([lo,la])=>[la,lo]);
    const lineCol=off?"#3a3f4a":(p.displayColor||(p.supplyFeeder?feederColor(p.supplyFeeder):null)||p.color);
    L.polyline(pts,{color:lineCol,
      weight:off?1.5:2.1,opacity:off?.45:.95,dashArray:off?"4 4":null}).addTo(lyr.conductors);
  }
}

function drawSwitchMarkers(layerKey, deviceClass){
  lyr[layerKey].clearLayers();
  if(!D.layers[layerKey]) return;
  for(const f of D.switches){
    const p=f.properties;
    if(p.deviceClass!==deviceClass) continue;
    if(D.feederFilter && p.feeder!==D.feederFilter) continue;
    const [lo,la]=f.geometry.coordinates;
    const cl=p.status===1;
    const sel=D.selectedSwitch===p.id;
    const out=sel?"outline:3px solid #00e5ff;outline-offset:2px;":"";
    const isDo=deviceClass==="dropout";
    const icon=di(isDo
      ?`<div class="m-do ${cl?"cl":"op"}" style="${out}"></div>`
      :`<div class="m-sw ${cl?"cl":"op"}" style="${out}"></div>`,
      isDo?[10,10]:[11,11]);
    L.marker([la,lo],{icon})
      .bindPopup(swPopup(f))
      .on("click",()=>{D.selectedSwitch=p.id;renderSwitches();})
      .addTo(lyr[layerKey]);
  }
}
function drawSwitches(){
  drawSwitchMarkers("switches","switch");
  drawSwitchMarkers("dropouts","dropout");
}
function swPopup(f){
  const p=f.properties,cl=p.status===1;
  const typeLbl=p.isRcBypass?"RC Bypass tie":(p.deviceClass==="dropout"?"Dropout (F)":"Switch");
  return `<div style="font-family:monospace;font-size:11px;min-width:175px">
    <b>${p.id}</b><br>
    Type:<span style="color:${p.isRcBypass?"#ffd600":p.deviceClass==="dropout"?"#fbbf24":"#00e5ff"}">${typeLbl}</span>
     · State:<span style="color:${cl?"#3fb950":"#f85149"}">${p.state}</span>
     · Feeder:${p.feeder} · ${p.kind}<br>
    ${p.presentPos!=null?`PRESENTPOS:<span style="color:#768390">${p.presentPos}</span><br>`:""}
    ${p.location?`<span style="color:#768390">${p.location}</span><br>`:""}
    <button onclick="doToggleSw('${p.id}')" style="margin-top:5px;width:100%;padding:4px;
      border:1px solid #00e5ff;background:transparent;color:#00e5ff;border-radius:4px;cursor:pointer">
      ${cl?"Open switch":"Close switch"}
    </button></div>`;
}

function drawReclosers(){
  lyr.reclosers.clearLayers();
  if(!D.layers.reclosers) return;
  for(const f of D.reclosers){
    const [lo,la]=f.geometry.coordinates;
    const p=f.properties;
    const cl=p.status===1;
    L.marker([la,lo],{icon:di(`<div class="m-rc${cl?"":" m-rc-open"}"></div>`,[10,9],[5,9])})
      .bindPopup(`<div style="font-family:monospace;font-size:11px;min-width:200px">
        <b style="color:#ffd600">⚡ Recloser</b> · <b>${p.id}</b><br>
        Feeder:<span style="color:#00e5ff">${p.feeder}</span> ·
        State:<span style="color:${cl?"#3fb950":"#ef4444"}">${p.state|| (cl?"CLOSE":"OPEN")}</span>
        ${p.location?`<br><span style="color:#768390">${p.location}</span>`:""}
        <div style="font-size:10px;color:#768390;margin-top:4px">ปลด recloser แทนเปิด tie ที่คุม section นี้</div>
        <button onclick="doToggleRc('${p.id}')" style="margin-top:6px;width:100%;padding:4px;
          border:1px solid ${cl?"#ef4444":"#3fb950"};background:transparent;
          color:${cl?"#ef4444":"#3fb950"};border-radius:4px;cursor:pointer">
          ${cl?"ปลด Recloser (OPEN)":"ปิด Recloser (CLOSE)"}
        </button></div>`)
      .addTo(lyr.reclosers);
  }
}

function drawTransformers(){
  lyr.transformers.clearLayers();
  if(!D.layers.transformers) return;
  for(const f of D.transformers){
    const [lo,la]=f.geometry.coordinates, p=f.properties;
    L.marker([la,lo],{icon:di('<div style="width:6px;height:6px;border-radius:50%;background:#fbbf24;box-shadow:0 0 4px rgba(251,191,36,.7)"></div>',[6,6])})
      .bindPopup(`<b>${p.id}</b><br>Feeder:${p.feeder}${p.rateKva?`<br>${p.rateKva} kVA`:""}<br><span style="color:#768390">${p.location||""}</span>`)
      .addTo(lyr.transformers);
  }
}

function drawSubstations(){
  lyr.substations.clearLayers();
  if(!D.layers.substations) return;
  for(const f of D.substations){
    const [lo,la]=f.geometry.coordinates, p=f.properties;
    const cl=p.status===1, v=p.virtual===true;
    // R7: virtual (tie-feed) CBs render as a hollow cyan diamond with
    // a dashed border so the operator can tell at a glance that the
    // upstream source is synthesised, not a real CB in pscb.json.
    const col = v ? (cl?"#06b6d4":"#475569") : (cl?"#fde047":"#ef4444");
    const glo = v ? (cl?"rgba(6,182,212,.55)":"rgba(71,85,105,.5)")
                  : (cl?"rgba(253,224,71,.7)" :"rgba(239,68,68,.7)");
    const bg  = v ? "transparent" : col;
    const brd = v ? `2px dashed ${col}` : `2px solid rgba(0,0,0,.5)`;
    const icon=di(`<div style="width:14px;height:14px;transform:rotate(45deg);background:${bg};
      border:${brd};box-shadow:0 0 0 2px rgba(0,0,0,.2),0 0 8px ${glo};border-radius:2px"></div>`,[14,14]);
    const head = v
      ? `<b style="color:#06b6d4">⤺ Virtual CB · Tie-feed</b> · <b>${p.id}</b>`
      : `<b style="color:#fde047">⚡ Source CB</b> · <b>${p.id}</b>`;
    const note = v
      ? `<div style="color:#06b6d4;font-size:10px;margin-top:3px">
           สังเคราะห์อัตโนมัติ — feeder นี้ไม่มี CB ใน pscb.json
           จึงสมมุติว่ามีแหล่งจ่ายจากสถานีข้างเคียง · กด toggle ได้</div>`
      : "";
    L.marker([la,lo],{icon})
      .bindPopup(`<div style="font-family:monospace;font-size:11px;min-width:200px">
        ${head}<br>
        Feeder:<span style="color:#00e5ff">${p.feeder}</span> · 
        State:<span style="color:${cl?"#3fb950":"#ef4444"}">${p.state}</span>
        ${p.opVolt?`<br>Voltage:${p.opVolt}`:""}
        ${p.location?`<br><span style="color:#768390">${p.location}</span>`:""}
        ${note}
        <br><button onclick="doToggleCB('${p.id}')" style="margin-top:5px;width:100%;padding:4px;
          border:1px solid ${cl?"#ef4444":"#3fb950"};background:transparent;
          color:${cl?"#ef4444":"#3fb950"};border-radius:4px;cursor:pointer">
          ${cl?"Open CB":"Close CB"}
        </button></div>`)
      .addTo(lyr.substations);
  }
}

function drawOutage(){
  lyr.outage.clearLayers();
  const sc=D.scada;
  if(!D.layers.outage || (!sc?.faultActive && !sc?.maintActive)) return;
  if(!D.outagePoly?.features?.length) return;
  for(const f of D.outagePoly.features){
    const ring=f.geometry.coordinates[0].map(([lo,la])=>[la,lo]);
    const p=f.properties||{};
    const fdCol=D.feeders.find(x=>x.id===p.feeder)?.color||"#f85149";
    const zoneLabel=sc.maintActive&&!sc.faultActive?"โซนบำรุงรักษา":"โซนไฟดับ (ตามสายจริง)";
    L.polygon(ring,{color:fdCol,weight:2,dashArray:"6 4",fillColor:fdCol,fillOpacity:.18,interactive:true})
      .bindPopup(`<div style="font-family:monospace;font-size:11px">
        <b style="color:#f85149">${zoneLabel}</b><br>
        ฟีดเดอร์โซนนี้: <b>${p.feeder||"?"}</b><br>
        ${sc.faultActive?`จุดฟอลต์: <b>${formatFaultFeeders(sc.faultFeeders, sc.faultFeeder)}</b><br>`:""}
        ${p.faultCoords?`พิกัด: ${p.faultCoords}<br>`:""}
        โหนดในพื้นที่: ${(p.nodesAffected||0).toLocaleString()}</div>`)
      .addTo(lyr.outage);
  }
  lyr.outage.bringToBack();
}

function drawFault(){
  lyr.fault.clearLayers();
  const f=D.fault;
  if(f.active && f.lat!=null && f.lon!=null){
    const coordTxt=`${f.lat.toFixed(6)}, ${f.lon.toFixed(6)}`;
    L.marker([f.lat,f.lon],{icon:di('<div class="m-fault"></div>',[18,18])})
      .bindPopup(`<div style="font-family:monospace;font-size:11px;min-width:200px">
        <b style="color:#f85149">⚠ จุดฟอลต์</b><br>
        ฟีดเดอร์: <b>${f.feeder||"?"}</b><br>
        พิกัด: <span id="fault-popup-coords">${coordTxt}</span><br>
        <button onclick="navigator.clipboard.writeText('${coordTxt}')" style="margin-top:6px;width:100%;padding:4px;
          border:1px solid #00e5ff;background:transparent;color:#00e5ff;border-radius:4px;cursor:pointer">
          คัดลอกพิกัด
        </button></div>`)
      .addTo(lyr.fault);
  }
}

function drawMaintenance(){
  lyr.maint.clearLayers();
  const m=D.maint;
  if(!m.active) return;
  if(m.startLat!=null && m.startLon!=null){
    L.marker([m.startLat,m.startLon],{icon:di('<div class="m-maint-start"></div>',[14,14])})
      .bindPopup(`<div style="font-family:monospace;font-size:11px">
        <b style="color:#3fb950">● จุดเริ่มงาน</b><br>
        ${m.startLat.toFixed(6)}, ${m.startLon.toFixed(6)}</div>`)
      .addTo(lyr.maint);
  }
  if(m.endLat!=null && m.endLon!=null){
    L.marker([m.endLat,m.endLon],{icon:di('<div class="m-maint-end"></div>',[14,14])})
      .bindPopup(`<div style="font-family:monospace;font-size:11px">
        <b style="color:#d29922">● จุดสิ้นสุดงาน</b><br>
        ${m.endLat.toFixed(6)}, ${m.endLon.toFixed(6)}</div>`)
      .addTo(lyr.maint);
  }
  if(m.startLat!=null && m.startLon!=null && m.endLat!=null && m.endLon!=null){
    L.polyline([[m.startLat,m.startLon],[m.endLat,m.endLon]],
      {color:"#d29922",weight:3,dashArray:"6 4",opacity:.85})
      .bindPopup(`<div style="font-family:monospace;font-size:11px">
        <b style="color:#d29922">โซนบำรุงรักษา</b><br>
        งาน: ${m.jobNumber||"—"} · ${m.jobName||"—"}<br>
        ฟีดเดอร์: <b>${m.feeder||"?"}</b></div>`)
      .addTo(lyr.maint);
  }
}

function parseCoordPair(latRaw, lonRaw){
  let latS=String(latRaw||"").trim();
  let lonS=String(lonRaw||"").trim();
  if((latS.includes(",")||/\s/.test(latS)) && !lonS){
    const parts=latS.split(/[,\s]+/).map(x=>x.trim()).filter(Boolean);
    if(parts.length>=2){ latS=parts[0]; lonS=parts[1]; }
  }
  const lat=parseFloat(latS.replace(",","."));
  const lon=parseFloat(lonS.replace(",","."));
  if(!Number.isFinite(lat)||!Number.isFinite(lon)) return null;
  if(lat<-90||lat>90||lon<-180||lon>180) return null;
  return {lat,lon};
}

function fillMapCenterCoords(){
  const c=map.getCenter();
  document.getElementById("ff-lat").value=c.lat.toFixed(6);
  document.getElementById("ff-lon").value=c.lng.toFixed(6);
  scheduleNearbyFeeders(c.lat, c.lng);
}

let _ffNearbyTimer=null;
let _ffNearbySeq=0;

function scheduleNearbyFeeders(lat, lon, maxM){
  clearTimeout(_ffNearbyTimer);
  const snapM=maxM ?? D.faultCoordSnapM ?? 20;
  _ffNearbyTimer=setTimeout(()=>refreshNearbyFeeders(lat, lon, snapM), 350);
}

function selectedFaultFeeders(){
  const list=document.getElementById("ff-feeder-list");
  if(!list) return [];
  return [...list.querySelectorAll('input[name="ff-feeder"]:checked')].map(cb=>cb.value);
}

function selectedFaultFeeder(){
  const arr=selectedFaultFeeders();
  return arr.length?arr[0]:null;
}

function formatFaultFeeders(feeders, primary){
  const arr=(feeders&&feeders.length)?feeders:(primary?[primary]:[]);
  if(!arr.length) return "none";
  return arr.length===1?arr[0]:arr.join(" · ");
}

async function refreshNearbyFeeders(lat, lon, maxM){
  const snapM=maxM ?? D.faultCoordSnapM ?? 20;
  const seq=++_ffNearbySeq;
  const wrap=document.getElementById("ff-feeder-wrap");
  const list=document.getElementById("ff-feeder-list");
  const hint=document.getElementById("ff-feeder-hint");
  if(!wrap||!list) return;

  if(!Number.isFinite(lat)||!Number.isFinite(lon)){
    wrap.classList.remove("show");
    list.innerHTML="";
    if(hint) hint.textContent="";
    return;
  }

  let data;
  try{
    data=await j(`/fault/nearby?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}&maxM=${encodeURIComponent(snapM)}`);
  }catch(_e){
    return;
  }
  if(seq!==_ffNearbySeq) return;

  const cands=data.candidates||[];
  if(!cands.length){
    wrap.classList.remove("show");
    list.innerHTML="";
    if(hint) hint.textContent="";
    return;
  }

  wrap.classList.add("show");
  const prev=new Set(selectedFaultFeeders());
  list.innerHTML=cands.map(c=>{
    const checked=prev.has(c.feeder)||(!prev.size&&c.feeder===data.suggested);
    return `<label><input type="checkbox" name="ff-feeder" value="${c.feeder}"${checked?" checked":""}>`
      +`<span>${c.feeder} · ~${c.distM} m</span></label>`;
  }).join("");
  if(hint){
    hint.textContent="เลือกฟีดเดอร์ที่เกี่ยวข้อง (ติ๊กได้หลายสาย) แล้วกด 「ตั้งจากพิกัด」";
  }
}

async function setFaultFromCoords(){
  const pair=parseCoordPair(document.getElementById("ff-lat").value,
                            document.getElementById("ff-lon").value);
  if(!pair){ alert("กรุณากรอกพิกัด Lat/Lon ให้ถูกต้อง (WGS84)"); return; }
  const list=document.getElementById("ff-feeder-list");
  const needsFeederList=!list?.querySelector('input[name="ff-feeder"]');
  if(needsFeederList){
    await refreshNearbyFeeders(pair.lat, pair.lon, D.faultCoordSnapM);
  }
  if(!selectedFaultFeeders().length){
    alert("กรุณาเลือกฟีดเดอร์อย่างน้อย 1 รายการก่อนตั้งฟอลต์");
    return;
  }
  await doSetFault(pair.lat, pair.lon);
  map.panTo([pair.lat, pair.lon]);
}

let fitted=false;
function fitBounds(){
  if(fitted||!D.conductors.length) return;
  const b=L.latLngBounds([]);let n=0;
  for(const c of D.conductors){
    for(const [lo,la] of c.geometry.coordinates){b.extend([la,lo]);if(++n>5000)break}
    if(n>5000)break;
  }
  if(b.isValid()){map.fitBounds(b,{padding:[40,40]});fitted=true;}
}

function energizedPct(sc){
  if(sc.customersTotal>0&&(sc.faultActive||sc.maintActive))
    return Math.round(sc.customersOn/sc.customersTotal*100);
  const tot=sc.nodesOn+sc.nodesOff;
  return tot>0?Math.round(sc.nodesOn/tot*100):0;
}

function updateHeader(){
  const sc=D.scada; if(!sc) return;
  const pct=energizedPct(sc);
  const pe=document.getElementById("h-pct");
  pe.textContent=pct+"%"; pe.className="stat-value "+(pct>=95?"good":pct>=80?"warn":"bad");
  document.getElementById("h-sw").textContent=`${sc.switchOpen}/${sc.switchTotal}`;
  const ce=document.getElementById("h-cb");
  ce.textContent=`${sc.cbOpen}/${sc.cbTotal}`; ce.className="stat-value "+(sc.cbOpen>0?"warn":"good");
  const fe=document.getElementById("h-ff");
  fe.textContent=formatFaultFeeders(sc.faultFeeders, sc.faultFeeder); fe.className="stat-value "+(sc.faultActive?"bad":"mute");
  document.getElementById("btn-clear").disabled=!sc.faultActive;
  document.getElementById("btn-plan").disabled=!sc.faultActive;
  document.getElementById("btn-clear-maint").disabled=!sc.maintActive;
  document.getElementById("btn-clear-maint").style.display=sc.maintActive?"inline-block":"none";
  document.getElementById("btn-maint-plan").disabled=!sc.maintActive;
  document.getElementById("btn-maint-plan").style.display=sc.maintActive?"inline-block":"none";
}

const LEG_IDS={switches:"swi",dropouts:"do",reclosers:"rec",transformers:"xfm",substations:"sub",outage:"out"};
function toggleLayer(name){
  D.layers[name]=!D.layers[name];
  document.getElementById("leg-"+LEG_IDS[name]).classList.toggle("on",D.layers[name]);
  if(D.layers[name]) lyr[name].addTo(map); else map.removeLayer(lyr[name]);
  ({switches:drawSwitches,dropouts:drawSwitches,reclosers:drawReclosers,transformers:drawTransformers,
    substations:drawSubstations,outage:drawOutage}[name])?.();
}

function tab(name,btn){
  document.querySelectorAll(".tab-btn").forEach(b=>b.classList.remove("active"));
  document.querySelectorAll(".tab-pane").forEach(p=>p.classList.remove("active"));
  btn.classList.add("active");
  document.getElementById("tab-"+name).classList.add("active");
}

function setFeeder(f){
  D.feederFilter=f; drawConductors(); drawSwitches(); renderFeeders(); renderSwitches();
}

function setSwClassFilter(cls,btn){
  D.swClassFilter=cls;
  document.querySelectorAll(".sw-filter button").forEach(b=>b.classList.remove("on"));
  if(btn) btn.classList.add("on");
  renderSwitches();
}

function renderSwitches(){
  const q=(document.getElementById("sw-search").value||"").toLowerCase(), ff=D.feederFilter, cf=D.swClassFilter;
  const list=D.switches.filter(f=>{
    const p=f.properties;
    if(ff&&p.feeder!==ff) return false;
    if(cf&&p.deviceClass!==cf) return false;
    if(!q) return true;
    return [p.id,p.feeder,p.location,p.kind,p.deviceClass].some(v=>String(v||"").toLowerCase().includes(q));
  });
  const el=document.getElementById("sw-list");
  if(!list.length){el.innerHTML='<div style="text-align:center;color:#768390;padding:20px;font-size:11px">ไม่พบ switch</div>';return;}
  el.innerHTML=list.map(f=>{
    const p=f.properties,cl=p.status===1,sel=D.selectedSwitch===p.id;
    return `<div class="sw-row${sel?" sel":""}" onclick="selectSw('${p.id}')">
      <span class="sw-dot" style="background:${cl?"#3fb950":"#f85149"};box-shadow:0 0 4px ${cl?"rgba(63,185,80,.6)":"rgba(248,81,73,.6)"}"></span>
      <div class="sw-info">
        <div class="sw-id">${p.id}</div>
        <div class="sw-sub">${p.deviceClass==="dropout"?"F":"S"} · ${p.feeder} · ${p.kind}${p.location?" · "+p.location:""}</div>
      </div>
      <button class="sw-tog" onclick="event.stopPropagation();doToggleSw('${p.id}')">${cl?"Open":"Close"}</button>
    </div>`;
  }).join("");
}

function selectSw(id){
  D.selectedSwitch=id; renderSwitches();
  const f=D.switches.find(s=>s.properties.id===id);
  if(f){const [lo,la]=f.geometry.coordinates;map.panTo([la,lo]);}
}

function renderFeeders(){
  const cbMap={};
  for(const s of D.substations){
    const f=s.properties.feeder; cbMap[f]=cbMap[f]||[];
    cbMap[f].push(s.properties.status);
  }
  const rows=[`<div class="fd-row${D.feederFilter===null?" sel":""}" onclick="setFeeder(null)">
    <span class="fd-dot" style="background:#444"></span>All feeders</div>`];
  for(const f of [...D.feeders].sort((a,b)=>b.edgeCount-a.edgeCount)){
    const cbs=cbMap[f.id]||[], srcOpen=cbs.length&&cbs.every(s=>s===0);
    const segTot=f.segmentsTotal||0, segOn=f.segmentsOn||0;
    const pct=segTot>0?Math.round(segOn/segTot*100):100;
    const dim=pct<95?'<span class="fd-cb">'+pct+'%</span>':"";
    rows.push(`<div class="fd-row${D.feederFilter===f.id?" sel":""}" onclick="setFeeder('${f.id}')">
      <span class="fd-dot" style="background:${f.color}"></span>
      <span>${f.id}</span>
      ${srcOpen?'<span class="fd-cb">⚡ CB open</span>':""}
      ${dim}
      ${!f.hasCb?'<span class="fd-no-cb">· no CB</span>':""}
      <span class="fd-cnt">${f.edgeCount.toLocaleString()}</span>
    </div>`);
  }
  document.getElementById("fd-list").innerHTML=rows.join("");
}

const FEEDER_TINT={
  PDA01:"#00e676",PDA02:"#ff5252",PDA03:"#ffd600",PDA04:"#40c4ff",
  PDA05:"#b388ff",PDA06:"#ff6e40",PDA07:"#69f0ae",PDA08:"#f06292",
  PDA09:"#ffab40",PDA10:"#ea80fc",KUA01:"#69f0ae",KUA07:"#ffd600",
};
function feederColor(id){
  return D.feeders.find(x=>x.id===id)?.color||FEEDER_TINT[id]||"#00e5ff";
}
function supplyFeederChips(feeders, label){
  if(!feeders||!feeders.length) return "";
  return `<div class="st-card good-b">
    <div class="st-title">${label}</div>
    <div style="font-size:10px;color:#768390;margin-bottom:6px">สีสายบนแผนที่ตรงกับฟีดเดอร์เหล่านี้ — ตรวจสอบก่อนคืนระบบเดิม</div>
    <div class="chips">${feeders.map(f=>{
      const c=feederColor(f);
      return `<span class="chip" style="border-color:${c};color:${c}">${f}</span>`;
    }).join("")}</div></div>`;
}

function renderStatus(){
  const sc=D.scada; if(!sc) return;
  const pct=energizedPct(sc);
  const showCust=sc.customersTotal>0&&(sc.faultActive||sc.maintActive);
  document.getElementById("st-list").innerHTML=[
    `<div class="st-card">
      <div class="st-title">⚡ Network Energization</div>
      <div style="font-size:10px;color:#768390;margin-bottom:6px">${sc.lineDisplayPhysical
        ?"⚡ โหมด real-time — สีสาย=ฟีดเดอร์ต้นทางจ่ายจริง · สายที่มีไฟแต่ไม่มีสวิทช์/RC เปิดกั้นแสดงสถานะเดียวกัน · โพลีก้อนเฉพาะจุดที่ยังดับ"
        :sc.lineDisplayIsolation
        ?"🔧 แยกวงจรแล้ว — โพลีก้อนยังเท่าเดิม · Energized ยังไม่รวมส่วนที่จ่ายย้อนกลับ"
        :sc.faultActive
        ?"โซนฟอลต์ตามทิศทาง load → tie · ทำตามแผนสวิทชิ่งแล้วจะอัปเดตเมื่อจ่ายย้อนกลับ"
        :sc.maintActive
        ?"โซนบำรุงรักษา active · สายในโซนงานแสดงเป็นดับ"
        :"แสดงสายเต็มระบบ 100% · สวิตช์ตาม PRESENTPOS เริ่มต้น"}</div>
      <div class="st-nums">
        <div class="st-num"><div class="st-val good">${sc.nodesOn.toLocaleString()}</div><div class="st-lbl">Nodes on</div></div>
        <div class="st-num"><div class="st-val bad">${sc.nodesOff.toLocaleString()}</div><div class="st-lbl">Nodes off</div></div>
        <div class="st-num"><div class="st-val">${pct}%</div><div class="st-lbl">Energized</div></div>
      </div>
      ${showCust?`<div class="st-nums" style="margin-top:8px;border-top:1px solid #2a3140;padding-top:8px">
        <div class="st-num"><div class="st-val good">${sc.customersOn.toLocaleString()}</div><div class="st-lbl">Users on (GIS)</div></div>
        <div class="st-num"><div class="st-val bad">${sc.customersOff.toLocaleString()}</div><div class="st-lbl">Users off</div></div>
        <div class="st-num"><div class="st-val">${sc.customersTotal.toLocaleString()}</div><div class="st-lbl">Users total</div></div>
      </div>`:""}</div>`,
    sc.lineDisplayPhysical && (sc.activeSupplyFeeders||[]).length
      ? supplyFeederChips(sc.activeSupplyFeeders,"⚡ ฟีดเดอร์ต้นทางจ่ายไฟ (ปัจจุบัน)")
      :"",
    sc.appBuild
      ? `<div class="st-card"><div class="st-title">Build</div>
         <div style="font-family:monospace;font-size:12px;color:#00e5ff">${sc.appBuild}</div>
         <div style="font-size:10px;color:#768390;margin-top:4px">ถ้าไม่ใช่ R75 ให้รีสตาร์ท python app.py แล้ว Ctrl+F5</div></div>`
      :"",
    `<div class="st-card${sc.cbOpen>0?" warn-b":""}">
      <div class="st-title">🔌 Source CBs</div>
      <div class="st-nums">
        <div class="st-num"><div class="st-val warn">${sc.cbOpen}</div><div class="st-lbl">Feeders open</div></div>
        <div class="st-num"><div class="st-val good">${sc.cbTotal-sc.cbOpen}</div><div class="st-lbl">Feeders closed</div></div>
        <div class="st-num"><div class="st-val">${sc.cbTotal}</div><div class="st-lbl">Active feeders</div></div>
      </div>
      ${(sc.feedersSourceOpen||[]).length?`<div class="chips">${sc.feedersSourceOpen.map(f=>`<span class="chip chip-w">${f}</span>`).join("")}</div>`:""}</div>`,
    `<div class="st-card">
      <div class="st-title">⏻ Tie Switches</div>
      <div class="st-nums">
        <div class="st-num"><div class="st-val">${sc.switchOpen}</div><div class="st-lbl">Open</div></div>
        <div class="st-num"><div class="st-val mute">${sc.switchTotal-sc.switchOpen}</div><div class="st-lbl">Closed</div></div>
        <div class="st-num"><div class="st-val">${sc.switchTotal}</div><div class="st-lbl">Total</div></div>
      </div></div>`,
    `<div class="st-card${sc.faultActive?" bad-b":""}">
      <div class="st-title">⚠ Active Fault</div>
      ${sc.faultActive
        ?`<div>Feeder: <b style="color:#f85149">${formatFaultFeeders(sc.faultFeeders, sc.faultFeeder)}</b>
           ${D.fault.lat?`<div style="font-size:10px;color:#768390;font-family:monospace;margin-top:3px">${D.fault.lat?.toFixed(5)}, ${D.fault.lon?.toFixed(5)}</div>`:""}
           <div style="margin-top:6px">
             <button class="btn-plan btn-sm" onclick="openPlanModal()" style="width:100%">
               ⚙ Generate Switching Plan
             </button>
           </div></div>`
        :`<div style="font-size:11px;color:#768390">ไม่มี fault · กด Place fault เพื่อจำลอง</div>`}
    </div>`,
    `<div class="st-card${sc.maintActive?" warn-b":""}">
      <div class="st-title">🔧 บำรุงรักษาระบบจำหน่าย</div>
      ${sc.maintActive
        ?`<div>งาน: <b style="color:#d29922">${sc.maintJobNumber||"—"}</b> · ${sc.maintJobName||"—"}<br>
           ฟีดเดอร์: <b>${sc.maintFeeder||"?"}</b>
           <div style="font-size:10px;color:#768390;font-family:monospace;margin-top:3px">${sc.maintCoords||"—"}</div>
           <div style="margin-top:6px">
             <button class="btn-plan btn-sm" onclick="openMaintPlanModal()" style="width:100%">
               ⚙ แผนสวิตช์งานบำรุงรักษา
             </button>
           </div></div>`
        :`<div style="font-size:11px;color:#768390">กด 🔧 บำรุงรักษา เพื่อกำหนดโซนปฏิบัติงาน</div>`}
    </div>`,
    (sc.feedersAffected||[]).length?
      `<div class="st-card">
        <div class="st-title">🔌 Feeders Affected</div>
        <div class="chips">${sc.feedersAffected.map(f=>`<span class="chip">${f}</span>`).join("")}</div>
      </div>`:"",
    (sc.feedersSourceOpen||[]).length?
      `<div class="st-card warn-b">
        <div class="st-title">⚡ Feeders — Source CB Open</div>
        <div class="chips">${sc.feedersSourceOpen.map(f=>`<span class="chip chip-w">${f}</span>`).join("")}</div>
      </div>`:"",
  ].join("");
}

async function refreshAfterSwitch(){
  D.pendingRefresh=false;
  D.mapBusy=false;
  await refreshLive();
}
async function doToggleRc(id){
  await fetch(`/reclosers/${encodeURIComponent(id)}/toggle`,{method:"POST"});
  await refreshAfterSwitch();
}
async function doToggleSw(id){
  await fetch(`/switches/${encodeURIComponent(id)}/toggle`,{method:"POST"});
  await refreshAfterSwitch();
}
async function doToggleCB(id){
  await fetch(`/substations/${encodeURIComponent(id)}/toggle`,{method:"POST"});
  await refreshAfterSwitch();
}

function toggleArm(){
  if(D.maintMode) toggleMaint();
  D.armMode=!D.armMode;
  document.getElementById("btn-arm").textContent=D.armMode?"❌ Cancel":"📍 Place fault";
  document.getElementById("btn-arm").className=D.armMode?"btn-danger btn-sm":"btn-out btn-sm";
  document.getElementById("fault-overlay").style.display=D.armMode?"block":"none";
  document.getElementById("fault-banner").style.display=D.armMode?"block":"none";
  document.getElementById("fault-form").style.display=D.armMode?"block":"none";
}

function toggleMaint(){
  if(D.armMode) toggleArm();
  D.maintMode=!D.maintMode;
  document.getElementById("btn-maint").textContent=D.maintMode?"❌ ปิด":"🔧 บำรุงรักษา";
  document.getElementById("btn-maint").className=D.maintMode?"btn-danger btn-sm":"btn-out btn-sm";
  document.getElementById("maint-banner").style.display=D.maintMode?"block":"none";
  document.getElementById("maint-form").style.display=D.maintMode?"block":"none";
}

function fillMaintStartFromMap(){
  const c=map.getCenter();
  document.getElementById("mf-start-lat").value=c.lat.toFixed(6);
  document.getElementById("mf-start-lon").value=c.lng.toFixed(6);
}

function fillMaintEndFromMap(){
  const c=map.getCenter();
  document.getElementById("mf-end-lat").value=c.lat.toFixed(6);
  document.getElementById("mf-end-lon").value=c.lng.toFixed(6);
}

async function setMaintenanceFromCoords(){
  const start=parseCoordPair(document.getElementById("mf-start-lat").value,
                             document.getElementById("mf-start-lon").value);
  const end=parseCoordPair(document.getElementById("mf-end-lat").value,
                           document.getElementById("mf-end-lon").value);
  if(!start||!end){ alert("กรุณากรอกพิกัดเริ่มต้นและสิ้นสุดให้ครบ (WGS84)"); return; }
  const jobName=document.getElementById("mf-job-name").value.trim();
  const jobNumber=document.getElementById("mf-job-no").value.trim();
  const r=await post("/maintenance",{
    startLat:start.lat,startLon:start.lon,
    endLat:end.lat,endLon:end.lon,
    jobName,jobNumber,
  });
  if(!r.active){
    alert(r.error||"กำหนดโซนงานไม่สำเร็จ");
    return;
  }
  D.maint={active:true,feeder:r.feeder,
    startLat:r.startLat,startLon:r.startLon,
    endLat:r.endLat,endLon:r.endLon,
    jobName:r.jobName,jobNumber:r.jobNumber};
  if(D.maintMode) toggleMaint();
  drawMaintenance();
  const bounds=L.latLngBounds([[start.lat,start.lon],[end.lat,end.lon]]);
  map.fitBounds(bounds,{padding:[60,60],maxZoom:16});
  await refreshLive();
}

async function clearMaintenance(){
  await fetch("/maintenance",{method:"DELETE"});
  D.maint={active:false,feeder:null,startLat:null,startLon:null,endLat:null,endLon:null,jobName:null,jobNumber:null};
  D.outagePoly={type:"FeatureCollection",features:[]};
  D.plan=null; D.planDone=0; D.planNormDone=0;
  document.getElementById("plan-norm-steps").innerHTML="";
  document.getElementById("btn-exec-norm").style.display="none";
  drawMaintenance(); drawOutage(); await refreshLive();
}

async function openMaintPlanModal(){
  setPlanPanelOpen(true);
  document.getElementById("plan-summary").innerHTML="⏳ กำลังวิเคราะห์แผนสวิตช์งานบำรุงรักษา…";
  document.getElementById("plan-next-hint").style.display="none";
  document.getElementById("plan-meta").innerHTML="";
  document.getElementById("plan-steps").innerHTML="";
  document.getElementById("plan-progress").textContent="—";
  document.getElementById("prog-fill").style.width="0%";
  document.getElementById("btn-exec-all").disabled=true;
  let plan;
  try{ plan=await post("/maintenance/switching-plan"); }
  catch(err){
    document.getElementById("plan-summary").innerHTML=`<span style="color:#f85149">❌ เกิดข้อผิดพลาด: ${err}</span>`;
    return;
  }
  if(plan.error){
    document.getElementById("plan-summary").innerHTML=`<span style="color:#f85149">❌ ${plan.error}</span>`;
    return;
  }
  D.plan=plan; D.planDone=0;
  renderPlan();
}

function handleFaultClick(e){
  if(!D.armMode) return;
  const rect=e.currentTarget.getBoundingClientRect();
  const latlng=map.containerPointToLatLng(L.point(e.clientX-rect.left,e.clientY-rect.top));
  document.getElementById("ff-lat").value=latlng.lat.toFixed(6);
  document.getElementById("ff-lon").value=latlng.lng.toFixed(6);
  refreshNearbyFeeders(latlng.lat, latlng.lng, D.faultMapClickSnapM);
}

async function doSetFault(lat,lon,mapClick=false){
  const cause=document.getElementById("ff-cause").value;
  const phase=document.getElementById("ff-phase").value;
  const feeders=selectedFaultFeeders();
  if(!feeders.length){
    alert("กรุณาเลือกฟีดเดอร์อย่างน้อย 1 รายการก่อนตั้งฟอลต์");
    return;
  }
  const body={lat,lon,cause,phase,feeders,feeder:feeders[0]};
  if(mapClick) body.mapClick=true;
  const f=await post("/fault", body);
  if(!f.active){
    alert(f.error||"ไม่พบสายไฟฟ้าใกล้พิกัดนี้ — ลองคลิกบนสายบนแผนที่หรือปรับพิกัดให้ใกล้ขึ้น");
    return;
  }
  D.fault={active:f.active,feeder:f.feeder,feeders:f.feeders||[f.feeder],lat:f.lat,lon:f.lon,cause,phase};
  document.getElementById("ff-lat").value=f.lat?.toFixed(6)||"";
  document.getElementById("ff-lon").value=f.lon?.toFixed(6)||"";
  D.pendingRefresh=false;
  D.mapBusy=false;
  if(D.armMode) toggleArm();
  drawFault();
  await refreshLive({force:true});
}

async function clearFault(){
  await fetch("/fault",{method:"DELETE"});
  D.fault={active:false,feeder:null,feeders:[],lat:null,lon:null};
  D.outagePoly={type:"FeatureCollection",features:[]};
  D.plan=null; D.planDone=0; D.planNormDone=0;
  document.getElementById("plan-norm-steps").innerHTML="";
  document.getElementById("btn-exec-norm").style.display="none";
  drawFault(); drawOutage(); await refreshLive();
}

async function openPlanModal(){
  setPlanPanelOpen(true);
  document.getElementById("plan-summary").innerHTML="⏳ กำลังวิเคราะห์ switching plan…";
  document.getElementById("plan-next-hint").style.display="none";
  document.getElementById("plan-meta").innerHTML="";
  document.getElementById("plan-steps").innerHTML="";
  document.getElementById("plan-norm-steps").innerHTML=
    '<div class="plan-section-label" style="color:#768390">รอสักครู่…</div>';
  document.getElementById("plan-progress").textContent="—";
  document.getElementById("prog-fill").style.width="0%";
  document.getElementById("btn-exec-all").disabled=true;
  document.getElementById("btn-exec-norm").style.display="none";
  let plan;
  try{ plan=await post("/switching-plan"); }
  catch(err){
    document.getElementById("plan-summary").innerHTML=`<span style="color:#f85149">❌ เกิดข้อผิดพลาด: ${err}</span>`;
    document.getElementById("plan-norm-steps").innerHTML="";
    return;
  }
  if(plan.error){
    document.getElementById("plan-summary").innerHTML=`<span style="color:#f85149">❌ ${plan.error}</span>`;
    document.getElementById("plan-norm-steps").innerHTML="";
    return;
  }
  D.plan=plan;
  D.planDone=plan.switchingPlanExecuted??0;
  D.planNormDone=0;
  renderPlan();
}
function setPlanPanelOpen(open){
  const panel=document.getElementById("plan-panel");
  const wrap=document.getElementById("map-wrap");
  if(open){
    const hdr=document.querySelector("header");
    const top=hdr?hdr.offsetHeight:53;
    panel.style.top=top+"px";
    panel.style.height=`calc(100vh - ${top}px)`;
    panel.classList.add("open");
    wrap.classList.add("plan-docked");
  }else{
    panel.classList.remove("open");
    wrap.classList.remove("plan-docked");
  }
  setTimeout(()=>map.invalidateSize(),180);
}

function closePlanModal(){
  setPlanPanelOpen(false);
}

function renderPlan(){
  const p=D.plan; if(!p) return;
  const isoSteps=p.isolationSteps??p.steps.filter(s=>s.action==="OPEN").length;
  const resSteps=p.restorationSteps??p.steps.filter(s=>s.action==="CLOSE").length;
  document.getElementById("plan-summary").innerHTML=
    `<b>${p.summary}</b><div style="margin-top:6px;color:#768390;font-size:11px">${p.operatorBrief||""}</div>`;
  const nextEl=document.getElementById("plan-next-hint");
  const nextTxt=p.steps[D.planDone]?.instructionTh||p.nextStepHint||"";
  if(nextTxt && D.planDone<p.steps.length){
    nextEl.style.display="block";
    nextEl.innerHTML=`<b>ขั้นถัดไป:</b> ${nextTxt}`;
  }else{
    nextEl.style.display="none";
  }
  const chips=p.planType==="maintenance"?[
    {label:"งาน",val:p.jobNumber||"—",col:"#d29922"},
    {label:"ชื่องาน",val:p.jobName||"—",col:"#d29922"},
    {label:"ฟีดเดอร์",val:p.faultFeeder||"?",col:"#a78bfa"},
    {label:"โซน",val:p.maintCoords||p.faultCoords||"—",col:"#00e5ff"},
    {label:"ดับ",val:`${(p.deenergizedNodes||0).toLocaleString()} nodes`,col:"#f85149"},
    {label:"คืนไฟได้",val:`${(p.totalRestorable||0).toLocaleString()} nodes`,col:"#3fb950"},
    {label:"แยกโซน",val:`${isoSteps} ขั้น`,col:"#f97316"},
    {label:"คืนระบบ",val:`${resSteps} ขั้น`,col:"#3fb950"},
  ]:[
    {label:"ฟีดเดอร์",val:p.faultFeeder||"?",col:"#a78bfa"},
    {label:"พิกัด",val:p.faultCoords||(p.faultLat!=null?`${p.faultLat.toFixed(6)}, ${p.faultLon.toFixed(6)}`:"—"),col:"#00e5ff"},
    {label:"สาเหตุ",val:p.faultCause||"—",col:"#d29922"},
    {label:"เฟส",val:p.faultPhase||"ALL",col:"#d29922"},
    {label:"ดับ",val:`${(p.deenergizedNodes||0).toLocaleString()} nodes`,col:"#f85149"},
    {label:"คืนไฟได้",val:`${(p.totalRestorable||0).toLocaleString()} nodes`,col:"#3fb950"},
    {label:"แยกฟอลต์",val:`${isoSteps} ขั้น`,col:"#f97316"},
    {label:"คืนไฟ",val:`${resSteps} ขั้น`,col:"#3fb950"},
    ...(p.normalizationCount?[{label:"คืนระบบเดิม",val:`${p.normalizationCount} ขั้น`,col:"#22d3ee"}]:[]),
    ...(p.kuaLineEndSource?[{label:"KUA",val:"กระแสจากปลายสาย",col:"#22d3ee"}]:[]),
  ];
  document.getElementById("plan-meta").innerHTML=chips.map(c=>
    `<span class="meta-chip" style="border-color:${c.col}44;color:${c.col}">
      <span style="color:#768390;font-size:9px">${c.label}: </span>${c.val}
    </span>`).join("");
  renderPlanSteps();
  renderNormSteps();
  document.getElementById("btn-exec-all").disabled=(p.steps.length===0||D.planDone>=p.steps.length);
  const normBtn=document.getElementById("btn-exec-norm");
  if(p.normalizationSteps&&p.normalizationSteps.length){
    normBtn.style.display="inline-block";
    normBtn.disabled=(D.planNormDone>=p.normalizationSteps.length);
  }else{
    normBtn.style.display="none";
  }
  document.getElementById("btn-copy-plan").disabled=!p.steps.length&&!p.normalizationSteps?.length;
  updatePlanProgress();
}

function buildPlanDispatchText(){
  const p=D.plan; if(!p) return "";
  const lines=[
    "=== PEA SPARK · แผนสวิตช์ ===",
    p.operatorBrief||p.summary,
    `พิกัด: ${p.faultCoords||"—"}`,
    "",
  ];
  let lastSection="";
  for(const step of p.steps){
    if(step.section && step.section!==lastSection){
      lastSection=step.section;
      lines.push(lastSection==="isolation"?"--- แยกจุดฟอลต์ ---":"--- คืนไฟ ---");
    }
    const mark=step.step<=D.planDone?"[x]":"[ ]";
    lines.push(`${mark} ${step.step}. ${step.instructionTh||step.reason}`);
  }
  if(p.normalizationSteps&&p.normalizationSteps.length){
    lines.push("","--- คืนระบบเดิมหลังซ่อม ---");
    for(const step of p.normalizationSteps){
      const mark=step.step<=D.planNormDone?"[x]":"[ ]";
      lines.push(`${mark} ${step.step}. ${step.instructionTh||step.reason}`);
    }
  }
  return lines.join("\n");
}

async function copyPlanDispatch(){
  const txt=buildPlanDispatchText();
  if(!txt) return;
  try{
    await navigator.clipboard.writeText(txt);
    const btn=document.getElementById("btn-copy-plan");
    const old=btn.textContent;
    btn.textContent="✓ คัดลอกแล้ว";
    setTimeout(()=>{btn.textContent=old;},1500);
  }catch(e){ alert("คัดลอกไม่สำเร็จ: "+e); }
}

function focusSwitchOnMap(switchId){
  let f=D.switches.find(s=>s.properties.id===switchId);
  if(!f) f=D.reclosers.find(r=>r.properties.id===switchId);
  if(!f) return;
  const [lo,la]=f.geometry.coordinates;
  D.selectedSwitch=switchId;
  map.setView([la,lo],Math.max(map.getZoom(),16),{animate:true});
  renderSwitches();
  drawReclosers();
}

function renderPlanSteps(){
  const p=D.plan;
  if(!p||!p.steps.length){
    document.getElementById("plan-steps").innerHTML=
      '<div style="text-align:center;color:#768390;padding:24px;font-size:12px">ไม่มีขั้นตอนที่แนะนำ</div>';
    return;
  }
  let html="", lastSection="";
  p.steps.forEach((step,i)=>{
    if(step.section && step.section!==lastSection){
      lastSection=step.section;
      const lbl=step.section==="isolation"?"① แยกจุดฟอลต์":"② คืนระบบ";
      html+=`<div class="plan-section-label">${lbl}</div>`;
    }
    const done=i<D.planDone, active=i===D.planDone, isOpen=step.action==="OPEN";
    const isNote=step.action==="NOTE";
    const btnLabel=isOpen?"เปิดสวิตช์":"ปิดสวิตช์";
    html+=`<div class="plan-step${done?" done":active?" active-step":""}" id="plan-step-${i}">
      <div class="step-num" style="border-color:${done?"#238636":active?"#a78bfa":"#30363d"};
           background:${done?"rgba(35,134,54,.15)":active?"rgba(139,92,246,.15)":"transparent"};
           color:${done?"#3fb950":active?"#a78bfa":"#768390"}">
        ${done?"✓":step.step}
      </div>
      <div class="step-body">
        ${isNote?"":`<div><span class="step-action action-${step.action}">${step.action}</span>
             <span class="step-sw">${step.switchId}</span>
             ${step.deviceType==="recloser"?'<span style="color:#ffd600;font-size:10px"> · RC</span>':""}</div>`}
        <div class="step-instruction">${step.instructionTh||step.reason}</div>
        ${isNote?"":`<div class="step-feeder">ฟีดเดอร์ ${step.feeder}${step.location?" · "+step.location:""}</div>`}
        <div class="step-reason">${step.reason}</div>
        ${step.nodesRestored>0
          ?`<div class="step-restore">+${step.nodesRestored.toLocaleString()} nodes คืนไฟ</div>`:""}
      </div>
      <div class="step-actions">
        ${isNote?(done?`<span style="color:#3fb950;font-size:12px">✓ ยืนยันแล้ว</span>`
          :`<button class="btn-sm btn-plan" onclick="executeStep(${i})" ${i!==D.planDone?"disabled":""}>✓ ยืนยันปลายสาย</button>`)
          :`<button type="button" class="btn-map" onclick="focusSwitchOnMap('${step.switchId}')">📍 แผนที่</button>
        ${done?`<span style="color:#3fb950;font-size:12px">✓ เสร็จแล้ว</span>`
              :`<button class="btn-sm ${isOpen?"btn-danger":"btn-success"}"
                  onclick="executeStep(${i})" ${i!==D.planDone?"disabled":""}>
                  ▶ ${btnLabel}</button>`}`}
      </div>
    </div>`;
  });
  document.getElementById("plan-steps").innerHTML=html;
}

function renderNormSteps(){
  const p=D.plan;
  const el=document.getElementById("plan-norm-steps");
  if(!p||!p.normalizationSteps||!p.normalizationSteps.length){
    if(el) el.innerHTML=""; return;
  }
  let html=`<div class="plan-section-label" style="color:#22d3ee;border-top:1px solid #30363d;padding-top:10px;margin-top:4px">③ คืนระบบเดิมหลังซ่อม (${p.normalizationSteps.length} ขั้น)</div>`;
  p.normalizationSteps.forEach((step,i)=>{
    const done=i<D.planNormDone, active=i===D.planNormDone;
    const isNote=step.action==="NOTE";
    const isOpen=step.action==="OPEN";
    html+=`<div class="plan-step${done?" done":active?" active-step":""}" id="plan-norm-step-${i}">
      <div class="step-num" style="border-color:${done?"#238636":active?"#22d3ee":"#30363d"};
           background:${done?"rgba(35,134,54,.15)":active?"rgba(34,211,238,.12)":"transparent"};
           color:${done?"#3fb950":active?"#22d3ee":"#768390"}">
        ${done?"✓":step.step}
      </div>
      <div class="step-body">
        ${isNote?"":`<div><span class="step-action action-${step.action}">${step.action}</span>
             <span class="step-sw">${step.switchId}</span>
             ${step.deviceType==="recloser"?'<span style="color:#ffd600;font-size:10px"> · RC</span>':""}</div>`}
        <div class="step-instruction">${step.instructionTh||step.reason}</div>
        ${isNote?"":`<div class="step-feeder">ฟีดเดอร์ ${step.feeder}${step.location?" · "+step.location:""}</div>`}
        <div class="step-reason">${step.reason}</div>
      </div>
      <div class="step-actions">
        ${isNote?(done?`<span style="color:#3fb950;font-size:12px">✓ ยืนยันแล้ว</span>`
          :`<button class="btn-sm btn-plan" onclick="executeNormStep(${i})" ${i!==D.planNormDone?"disabled":""}>✓ ยืนยัน</button>`)
          :`<button type="button" class="btn-map" onclick="focusSwitchOnMap('${step.switchId}')">📍 แผนที่</button>
        ${done?`<span style="color:#3fb950;font-size:12px">✓ เสร็จแล้ว</span>`
              :`<button class="btn-sm ${isOpen?"btn-danger":"btn-success"}"
                  onclick="executeNormStep(${i})" ${i!==D.planNormDone?"disabled":""}>
                  ▶ ${isOpen?"เปิด":"ปิด"}</button>`}`}
      </div>
    </div>`;
  });
  el.innerHTML=html;
}

function updatePlanProgress(){
  const p=D.plan; if(!p) return;
  const total=p.steps.length, done=D.planDone;
  const pct=total>0?Math.round(done/total*100):0;
  const next=p.steps[done];
  document.getElementById("plan-progress").textContent=
    done<total
      ?`ดำเนินการแล้ว ${done}/${total} (${pct}%) · ถัดไป: ${next?.instructionTh||"—"}`
      :`✅ ดำเนินการครบ ${total} ขั้นแล้ว`;
  const nextEl=document.getElementById("plan-next-hint");
  if(next && done<total){
    nextEl.style.display="block";
    nextEl.innerHTML=`<b>ขั้นถัดไป:</b> ${next.instructionTh||next.reason}`;
  }else if(done>=total && total>0){
    const normTotal=p.normalizationSteps?.length||0;
    if(normTotal && D.planNormDone<normTotal){
      nextEl.style.display="block";
      nextEl.innerHTML="<b>สถานะ:</b> แผนคืนไฟครบแล้ว — ดำเนินการคืนระบบเดิมหลังซ่อม";
    }else{
      nextEl.style.display="block";
      nextEl.innerHTML="<b>สถานะ:</b> แผนดำเนินการครบแล้ว";
    }
  }else{
    nextEl.style.display="none";
  }
  document.getElementById("prog-fill").style.width=pct+"%";
  document.getElementById("btn-exec-all").disabled=(done>=total);
}

function patchDeviceStatus(id, action, newStatus){
  const st=newStatus!=null?newStatus:(action==="CLOSE"?1:0);
  const state=st?"CLOSE":"OPEN";
  for(const f of D.switches){
    if(f.properties.id===id){f.properties.status=st;f.properties.state=state;return;}
  }
  for(const f of D.reclosers){
    if(f.properties.id===id){f.properties.status=st;f.properties.state=state;return;}
  }
}

/** Immediate UI sync from execute response — do not wait for /live-refresh (R55/R75). */
function applyExecuteResponse(resp, step){
  if(resp.switchId && step.action!=="NOTE"){
    patchDeviceStatus(resp.switchId, resp.action, resp.newStatus);
    drawSwitches(); drawReclosers(); renderSwitches();
  }
  // Optional liveMap (legacy) — map paint prefers /live-refresh after status (R75).
  if(resp.liveMap?.conductors?.features && resp.liveMap?.scada){
    D.mapGen=(D.mapGen||0)+1;
    applyLiveBundle(resp.liveMap);
  }
  if(!D.scada) return;
  if(resp.lineDisplayPhysical!=null){
    D.scada.lineDisplayPhysical=resp.lineDisplayPhysical;
    D.scada.lineDisplayIsolation=!!D.scada.faultActive && !resp.lineDisplayPhysical;
  }
  if(resp.kuaLineEndAck!=null) D.scada.lineEndRestoreActive=resp.kuaLineEndAck;
  updateHeader(); renderStatus();
  const banner=document.getElementById("fault-banner");
  if(banner && D.scada.faultActive){
    banner.textContent=resp.lineDisplayPhysical
      ? "⚡ Real-time — สีสาย=ฟีดเดอร์ต้นทางจ่ายจริง · ดูแถบ Status ว่าใช้ฟีดเดอร์ไหนอยู่"
      : D.scada.lineDisplayIsolation
      ? "🔧 แยกวงจรแล้ว — กดยืนยันปลายสาย (ขั้น NOTE) เพื่อแสดงไฟย้อนจาก KUA01"
      : banner.textContent;
  }
}

async function executeStep(i){
  const p=D.plan; if(!p||i!==D.planDone) return;
  const step=p.steps[i];
  const hint=document.getElementById("plan-next-hint");
  if(hint){hint.style.display="block";hint.textContent="⏳ กำลังดำเนินการ…";}
  setMapProcessing(true,"กำลังดำเนินการขั้นตอน…");
  // R75: show OPEN/CLOSE (e.g. 7S-12) immediately; map refresh can take longer.
  if(step.action!=="NOTE" && step.switchId){
    patchDeviceStatus(step.switchId, step.action);
    drawSwitches(); drawReclosers(); renderSwitches();
  }
  try{
    const resp=await post(`/switching-plan/execute/${i+1}`,{
      action:step.action,
      switchId:step.switchId,
      planEffect:step.planEffect||null,
      instructionTh:step.instructionTh||step.reason||null,
    });
    D.planDone=resp.switchingPlanExecuted??(i+1);
    D.mapGen=(D.mapGen||0)+1;
    applyExecuteResponse(resp, step);
    renderPlanSteps(); updatePlanProgress();
    if(hint){
      hint.textContent=resp.lineDisplayPhysical
        ? "⏳ ยืนยันแล้ว — กำลังวาดสายจ่ายไฟบนแผนที่…"
        : step.action!=="NOTE"
        ? "✓ อัปเดตสถานะอุปกรณ์แล้ว · กำลังโหลดแผนที่…"
        : "✓ ยืนยันขั้นตอนแล้ว · กำลังโหลดแผนที่…";
    }
    await refreshLiveAfterPlanStep();
    const next=document.getElementById(`plan-step-${D.planDone}`);
    if(next) next.scrollIntoView({behavior:"smooth",block:"nearest"});
    if(hint){
      hint.textContent=resp.lineDisplayPhysical
        ? "✓ อัปเดตแผนที่แล้ว — แสดงสีฟีดเดอร์ต้นทางจ่ายจริง"
        : step.action==="NOTE" ? "✓ ยืนยันขั้นตอนแล้ว — รอขั้นถัดไป" : "✓ อัปเดตสถานะอุปกรณ์แล้ว";
    }
  }catch(err){
    if(step.action!=="NOTE" && step.switchId){
      patchDeviceStatus(step.switchId, step.action==="OPEN"?"CLOSE":"OPEN");
      drawSwitches(); drawReclosers(); renderSwitches();
    }
    alert("ดำเนินการไม่สำเร็จ: "+err); renderPlanSteps();
  }
  finally{ setMapProcessing(false); updatePlanProgress(); }
}

async function executeNormStep(i){
  const p=D.plan; if(!p||!p.normalizationSteps||i!==D.planNormDone) return;
  const step=p.normalizationSteps[i];
  try{
    await post(`/switching-plan/normalize/execute/${i+1}`,
      {action:step.action,switchId:step.switchId});
    if(step.action!=="NOTE") patchDeviceStatus(step.switchId, step.action);
    drawSwitches(); drawReclosers(); renderSwitches();
    D.planNormDone++; renderNormSteps();
    const normBtn=document.getElementById("btn-exec-norm");
    if(normBtn) normBtn.disabled=(D.planNormDone>=p.normalizationSteps.length);
    if(step.action!=="NOTE") await refreshLiveAfterPlanStep();
    const next=document.getElementById(`plan-norm-step-${D.planNormDone}`);
    if(next) next.scrollIntoView({behavior:"smooth",block:"nearest"});
  }catch(err){ alert("ดำเนินการไม่สำเร็จ: "+err); renderNormSteps(); }
}

async function executeAllNorm(){
  if(!D.plan||!D.plan.normalizationSteps) return;
  while(D.planNormDone<D.plan.normalizationSteps.length){
    await executeNormStep(D.planNormDone);
    await new Promise(r=>setTimeout(r,600));
  }
}

async function executeAll(){
  if(!D.plan) return;
  while(D.planDone<D.plan.steps.length){
    await executeStep(D.planDone);
    await new Promise(r=>setTimeout(r,600));
  }
  if(D.plan.normalizationSteps?.length){
    renderPlan();
    const normEl=document.getElementById("plan-norm-steps");
    if(normEl){
      normEl.scrollIntoView({behavior:"smooth",block:"start"});
    }
  }
}

let _refreshTimer=null;
function scheduleRefreshLive(){
  clearInterval(_refreshTimer);
  const active=D.fault?.active||D.scada?.faultActive||D.scada?.maintActive;
  const ms=active?30000:15000;
  _refreshTimer=setInterval(refreshLive,ms);
}

function wireFaultFormNearFeeders(){
  const onCoordInput=()=>{
    const pair=parseCoordPair(
      document.getElementById("ff-lat").value,
      document.getElementById("ff-lon").value,
    );
    if(pair) scheduleNearbyFeeders(pair.lat, pair.lon);
  };
  document.getElementById("ff-lat")?.addEventListener("input", onCoordInput);
  document.getElementById("ff-lon")?.addEventListener("input", onCoordInput);
}

wireFaultFormNearFeeders();
loadAll().then(()=>scheduleRefreshLive());
