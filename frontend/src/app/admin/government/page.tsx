"use client";
import { safeHref } from "@/lib/safe";
// V19.1 — Government Recruitment Core admin console. Same auth
// pattern as src/app/admin/page.tsx (shared X-Admin-Key header or an
// existing admin session token) and the same call() convention —
// this is an additive new route, it does not touch that page.
import {useEffect,useState} from "react";
import {API,formatApiError,token} from "@/lib/api";

type Tab="organizations"|"moderation"|"sources";

export default function GovernmentAdminPage(){
  const[key,setKey]=useState("");
  const[hasSession,setHasSession]=useState(false);
  const[tab,setTab]=useState<Tab>("moderation");
  const[msg,setMsg]=useState("");

  const[orgs,setOrgs]=useState<any[]>([]);
  const[orgForm,setOrgForm]=useState({name:"",short_name:"",govt_level:"",official_website:""});

  const[queue,setQueue]=useState<{total:number,jobs:any[]}>({total:0,jobs:[]});

  const[sources,setSources]=useState<any[]>([]);
  const[sourceForm,setSourceForm]=useState({source_name:"",official_url:"",collector_type:"official_html"});

  useEffect(()=>{setHasSession(!!token())},[]);

  async function call(path:string,method="GET",body?:any){
    const headers:Record<string,string>={"Content-Type":"application/json"};
    const t=token(); if(t) headers["Authorization"]=`Bearer ${t}`;
    if(key) headers["X-Admin-Key"]=key;
    const r=await fetch(`${API}/government${path}`,{method,headers,body:body?JSON.stringify(body):undefined});
    let j:any=null; try{j=await r.json()}catch{}
    if(!r.ok) throw new Error(formatApiError(j,"Government admin request failed"));
    return j;
  }

  // Approve/reject reuse the existing generic admin review endpoints
  // (POST /admin/jobs/{id}/publish|reject) rather than duplicating
  // that logic — this hits /admin directly, not /government.
  async function callAdmin(path:string,method="GET"){
    const headers:Record<string,string>={};
    const t=token(); if(t) headers["Authorization"]=`Bearer ${t}`;
    if(key) headers["X-Admin-Key"]=key;
    const r=await fetch(`${API}/admin${path}`,{method,headers});
    let j:any=null; try{j=await r.json()}catch{}
    if(!r.ok) throw new Error(formatApiError(j,"Admin request failed"));
    return j;
  }

  async function loadOrgs(){ setOrgs(await call("/organizations")); }
  async function loadQueue(){ setQueue(await call("/moderation/queue")); }
  async function loadSources(){ setSources(await call("/sources")); }

  async function openWorkspace(){
    try{
      setMsg("");
      await Promise.all([loadOrgs(),loadQueue(),loadSources()]);
    }catch(e:any){ setMsg(e.message); }
  }

  async function createOrg(){
    try{
      await call("/organizations","POST",{...orgForm, govt_level: orgForm.govt_level||undefined});
      setOrgForm({name:"",short_name:"",govt_level:"",official_website:""});
      loadOrgs();
    }catch(e:any){ setMsg(e.message); }
  }
  async function archiveOrg(id:number){ await call(`/organizations/${id}`,"DELETE"); loadOrgs(); }

  async function approveJob(id:number){ try{ await callAdmin(`/jobs/${id}/publish`,"POST"); loadQueue(); }catch(e:any){ setMsg(e.message); } }
  async function rejectJob(id:number){ try{ await callAdmin(`/jobs/${id}/reject`,"POST"); loadQueue(); }catch(e:any){ setMsg(e.message); } }

  async function registerSource(){
    try{
      await call("/sources","POST",sourceForm);
      setSourceForm({source_name:"",official_url:"",collector_type:"official_html"});
      loadSources();
    }catch(e:any){ setMsg(e.message); }
  }
  async function toggleSource(id:number,status:string){
    await call(`/sources/${id}`,"PATCH",{status});
    loadSources();
  }

  return <main className="container page">
    <span className="eyebrow">Government recruitment core — admin</span>
    <h1>Organizations, moderation & sources</h1>
    <div className="card form">
      {hasSession
        ? <p className="muted">Signed in as admin — using your session automatically.</p>
        : <input className="field" type="password" placeholder="Admin key" value={key} onChange={e=>setKey(e.target.value)}/>}
      <button className="btn" onClick={openWorkspace}>Open government workspace</button>
      {msg && <p className="error">{msg}</p>}
    </div>

    <div className="filters">
      <button className={tab==="moderation"?"chip chip-active":"chip"} onClick={()=>setTab("moderation")}>Moderation queue ({queue.total})</button>
      <button className={tab==="organizations"?"chip chip-active":"chip"} onClick={()=>setTab("organizations")}>Organizations ({orgs.length})</button>
      <button className={tab==="sources"?"chip chip-active":"chip"} onClick={()=>setTab("sources")}>Source registry ({sources.length})</button>
    </div>

    {tab==="moderation" && <>
      <h2>Government jobs pending review</h2>
      <p className="muted">Approve/reject reuse the existing admin review endpoints — this is a filtered view, not a separate pipeline.</p>
      <div className="jobs">{queue.jobs.map((j:any)=>
        <div className="card" key={j.id}>
          <b>{j.title}</b>
          <p>{j.organization}{j.ad_number?` · Advt No. ${j.ad_number}`:""}</p>
          <p className="muted">{j.source_name||"Manual entry"} · {j.location}</p>
          {j.official_url && <a className="linkbtn" target="_blank" rel="noreferrer" href={safeHref(j.official_url)}>Inspect official source</a>}
          <div className="actions">
            <button className="btn" onClick={()=>approveJob(j.id)}>Approve</button>
            <button className="btn secondary" onClick={()=>rejectJob(j.id)}>Reject</button>
          </div>
        </div>
      )}
      {queue.jobs.length===0 && <p className="empty">Nothing pending review.</p>}
      </div>
    </>}

    {tab==="organizations" && <>
      <h2>Add a government organization</h2>
      <div className="card form">
        <input className="field" placeholder="Name (e.g. Staff Selection Commission)" value={orgForm.name} onChange={e=>setOrgForm({...orgForm,name:e.target.value})}/>
        <input className="field" placeholder="Short name (e.g. SSC)" value={orgForm.short_name} onChange={e=>setOrgForm({...orgForm,short_name:e.target.value})}/>
        <select className="field" value={orgForm.govt_level} onChange={e=>setOrgForm({...orgForm,govt_level:e.target.value})}>
          <option value="">Government level…</option>
          {["Central","State","PSU","University","Board","Commission"].map(l=><option key={l} value={l}>{l}</option>)}
        </select>
        <input className="field" placeholder="Official website URL" value={orgForm.official_website} onChange={e=>setOrgForm({...orgForm,official_website:e.target.value})}/>
        <button className="btn" onClick={createOrg}>Create organization</button>
      </div>
      <h2>Organizations</h2>
      <div className="jobs">{orgs.map((o:any)=>
        <div className="card" key={o.id}>
          <b>{o.name}</b>{o.short_name && <span className="pill">{o.short_name}</span>}
          <p className="muted">{o.govt_level||"Level not set"}</p>
          {o.official_website && <a className="linkbtn" target="_blank" rel="noreferrer" href={safeHref(o.official_website)}>Official website</a>}
          <div className="actions"><button className="btn secondary" onClick={()=>archiveOrg(o.id)}>Archive</button></div>
        </div>
      )}</div>
    </>}

    {tab==="sources" && <>
      <h2>Register a source</h2>
      <p className="muted">Registering a source only catalogs it — it does not enable scraping. Live collectors are configured separately in app/ingestion/sources.py, per the V19.1 scope (framework only).</p>
      <div className="card form">
        <input className="field" placeholder="Source name (e.g. UPSC)" value={sourceForm.source_name} onChange={e=>setSourceForm({...sourceForm,source_name:e.target.value})}/>
        <input className="field" placeholder="Official URL" value={sourceForm.official_url} onChange={e=>setSourceForm({...sourceForm,official_url:e.target.value})}/>
        <select className="field" value={sourceForm.collector_type} onChange={e=>setSourceForm({...sourceForm,collector_type:e.target.value})}>
          {["official_html","rss","xml","json_api","selenium","playwright"].map(c=><option key={c} value={c}>{c}</option>)}
        </select>
        <button className="btn" onClick={registerSource}>Register source</button>
      </div>
      <h2>Registered sources</h2>
      <div className="jobs">{sources.map((s:any)=>
        <div className="card" key={s.id}>
          <b>{s.source_name}</b><span className="pill">{s.collector_type}</span>
          <p className="muted">Status: {s.status} · Errors: {s.error_count}</p>
          {s.official_url && <a className="linkbtn" target="_blank" rel="noreferrer" href={safeHref(s.official_url)}>Official URL</a>}
          <div className="actions">
            {s.status!=="active" && <button className="btn" onClick={()=>toggleSource(s.id,"active")}>Activate</button>}
            {s.status==="active" && <button className="btn secondary" onClick={()=>toggleSource(s.id,"paused")}>Pause</button>}
          </div>
        </div>
      )}</div>
    </>}
  </main>;
}
