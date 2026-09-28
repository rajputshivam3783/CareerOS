"use client";
import { safeHref } from "@/lib/safe";
// V19.2 — Official Source Adapter Framework: the professional admin
// Source Management dashboard. Same auth pattern as
// src/app/admin/government/page.tsx (shared X-Admin-Key header or an
// existing admin session token) — this is a new, additive route; it
// does not touch admin/government/page.tsx, which keeps its own
// simpler "register a source" tab exactly as it was in V19.1.
import {useEffect,useMemo,useState} from "react";
import {API,formatApiError,token} from "@/lib/api";

type Source = {
  id:number; source_name:string; official_url?:string; collector_type:string;
  schedule?:string; status:string; organization?:string; govt_level?:string; category?:string;
  priority:number; last_run_at?:string; last_success_at?:string; last_failure_at?:string;
  last_latency_ms?:number; availability_pct?:number; retry_count:number; error_count:number;
  circuit_state:string; consecutive_failures:number;
};

type Stats = {
  total_sources:number; sources_by_status:Record<string,number>; open_circuits:number;
  total_runs:number; successful_runs:number; failed_runs:number;
  success_rate_pct:number|null; failure_rate_pct:number|null;
  total_jobs_created:number; unresolved_dead_letters:number;
};

const PAGE_SIZE = 12;
const COLLECTOR_TYPES = ["official_html","html_list","rss","xml","json_api","pdf_metadata","sitemap","selenium","playwright"];
const STATUSES = ["active","paused","disabled"];

export default function SourceDashboardPage(){
  const[key,setKey]=useState("");
  const[hasSession,setHasSession]=useState(false);
  const[msg,setMsg]=useState("");
  const[loading,setLoading]=useState(false);

  const[sources,setSources]=useState<Source[]>([]);
  const[stats,setStats]=useState<Stats|null>(null);

  const[statusFilter,setStatusFilter]=useState<string>("");
  const[typeFilter,setTypeFilter]=useState<string>("");
  const[search,setSearch]=useState("");
  const[page,setPage]=useState(1);

  const[selected,setSelected]=useState<Source|null>(null);
  const[health,setHealth]=useState<any>(null);
  const[runs,setRuns]=useState<any[]>([]);
  const[logs,setLogs]=useState<any[]>([]);
  const[detailLoading,setDetailLoading]=useState(false);

  const[form,setForm]=useState({source_name:"",official_url:"",collector_type:"official_html",organization:"",govt_level:"",category:"",schedule:"daily"});

  useEffect(()=>{ setHasSession(!!token()); },[]);

  async function call(path:string,method="GET",body?:any){
    const headers:Record<string,string>={"Content-Type":"application/json"};
    const t=token(); if(t) headers["Authorization"]=`Bearer ${t}`;
    if(key) headers["X-Admin-Key"]=key;
    const r=await fetch(`${API}/government${path}`,{method,headers,body:body?JSON.stringify(body):undefined});
    let j:any=null; try{j=await r.json()}catch{}
    if(!r.ok) throw new Error(formatApiError(j,"Source dashboard request failed"));
    return j;
  }

  async function loadAll(){
    try{
      setLoading(true); setMsg("");
      const [srcs, st] = await Promise.all([call("/sources"), call("/sources/statistics")]);
      setSources(srcs); setStats(st);
    }catch(e:any){ setMsg(e.message); }
    finally{ setLoading(false); }
  }

  async function openDetail(s:Source){
    setSelected(s); setDetailLoading(true); setHealth(null); setRuns([]); setLogs([]);
    try{
      const [h,r,l] = await Promise.all([
        call(`/sources/${s.id}/health`),
        call(`/sources/${s.id}/runs?limit=10`),
        call(`/sources/${s.id}/logs?limit=40`),
      ]);
      setHealth(h); setRuns(r.runs); setLogs(l.logs);
    }catch(e:any){ setMsg(e.message); }
    finally{ setDetailLoading(false); }
  }

  async function runNow(s:Source){
    try{ setMsg(""); await call(`/sources/${s.id}/run`,"POST"); await loadAll(); if(selected?.id===s.id) openDetail(s); }
    catch(e:any){ setMsg(e.message); }
  }

  async function setStatus(s:Source,status:string){
    try{ await call(`/sources/${s.id}`,"PATCH",{status}); loadAll(); }
    catch(e:any){ setMsg(e.message); }
  }

  async function register(){
    try{
      setMsg("");
      await call("/sources","POST",{
        ...form,
        govt_level: form.govt_level||undefined,
        category: form.category||undefined,
        organization: form.organization||undefined,
      });
      setForm({source_name:"",official_url:"",collector_type:"official_html",organization:"",govt_level:"",category:"",schedule:"daily"});
      loadAll();
    }catch(e:any){ setMsg(e.message); }
  }

  async function seedFramework(){
    try{ setMsg(""); const res=await call("/sources/seed-framework","POST"); setMsg(`Seeded ${res.created.length} organization(s).`); loadAll(); }
    catch(e:any){ setMsg(e.message); }
  }

  const filtered = useMemo(()=>{
    return sources.filter(s=>{
      if(statusFilter && s.status!==statusFilter) return false;
      if(typeFilter && s.collector_type!==typeFilter) return false;
      if(search && !(`${s.source_name} ${s.organization||""} ${s.category||""}`.toLowerCase().includes(search.toLowerCase()))) return false;
      return true;
    });
  },[sources,statusFilter,typeFilter,search]);

  const pageCount = Math.max(1, Math.ceil(filtered.length/PAGE_SIZE));
  const pageItems = filtered.slice((page-1)*PAGE_SIZE, page*PAGE_SIZE);

  useEffect(()=>{ setPage(1); },[statusFilter,typeFilter,search]);

  return <main className="container page">
    <span className="eyebrow">Official source adapter framework</span>
    <h1>Source Management</h1>
    <p className="muted">Enable/disable adapters, run them manually, and inspect health, runs, and logs — every adapter here is built on the shared V19.2 plugin framework, not a bespoke scraper per organization.</p>

    <div className="card form">
      {hasSession
        ? <p className="muted">Signed in as admin — using your session automatically.</p>
        : <input className="field" type="password" placeholder="Admin key" value={key} onChange={e=>setKey(e.target.value)}/>}
      <div className="actions">
        <button className="btn" onClick={loadAll}>Open source dashboard</button>
        <button className="btn secondary" onClick={seedFramework}>Seed framework organizations</button>
      </div>
      {msg && <p className="error">{msg}</p>}
    </div>

    {stats && <div className="statgrid">
      <div className="statcard"><b>{stats.total_sources}</b><span>TOTAL SOURCES</span></div>
      <div className="statcard"><b>{stats.sources_by_status.active||0}</b><span>ACTIVE</span></div>
      <div className="statcard"><b>{stats.open_circuits}</b><span>OPEN CIRCUITS</span></div>
      <div className="statcard"><b>{stats.success_rate_pct ?? "—"}{stats.success_rate_pct!=null?"%":""}</b><span>RUN SUCCESS RATE</span></div>
      <div className="statcard"><b>{stats.total_jobs_created}</b><span>JOBS CREATED</span></div>
      <div className="statcard"><b>{stats.unresolved_dead_letters}</b><span>DEAD LETTERS</span></div>
    </div>}

    <h2>Register a source</h2>
    <div className="card form">
      <input className="field" placeholder="Source name" value={form.source_name} onChange={e=>setForm({...form,source_name:e.target.value})}/>
      <input className="field" placeholder="Official URL" value={form.official_url} onChange={e=>setForm({...form,official_url:e.target.value})}/>
      <select className="field" value={form.collector_type} onChange={e=>setForm({...form,collector_type:e.target.value})}>
        {COLLECTOR_TYPES.map(c=><option key={c} value={c}>{c}</option>)}
      </select>
      <input className="field" placeholder="Organization" value={form.organization} onChange={e=>setForm({...form,organization:e.target.value})}/>
      <select className="field" value={form.govt_level} onChange={e=>setForm({...form,govt_level:e.target.value})}>
        <option value="">Government level…</option>
        {["Central","State","PSU","University","Board","Commission"].map(l=><option key={l} value={l}>{l}</option>)}
      </select>
      <input className="field" placeholder="Category" value={form.category} onChange={e=>setForm({...form,category:e.target.value})}/>
      <select className="field" value={form.schedule} onChange={e=>setForm({...form,schedule:e.target.value})}>
        {["manual","hourly","daily"].map(s=><option key={s} value={s}>{s}</option>)}
      </select>
      <button className="btn" onClick={register}>Register source</button>
    </div>

    <h2>Sources ({filtered.length})</h2>
    <div className="filters">
      <input className="field" placeholder="Search name, organization, category…" value={search} onChange={e=>setSearch(e.target.value)} style={{maxWidth:280}}/>
      <select className="field" value={statusFilter} onChange={e=>setStatusFilter(e.target.value)} style={{maxWidth:160}}>
        <option value="">All statuses</option>
        {STATUSES.map(s=><option key={s} value={s}>{s}</option>)}
      </select>
      <select className="field" value={typeFilter} onChange={e=>setTypeFilter(e.target.value)} style={{maxWidth:180}}>
        <option value="">All collector types</option>
        {COLLECTOR_TYPES.map(c=><option key={c} value={c}>{c}</option>)}
      </select>
    </div>

    {loading && <p className="loading">Loading sources…</p>}
    {!loading && filtered.length===0 && <p className="empty">No sources match these filters.</p>}

    {!loading && filtered.length>0 && <>
      <table className="srctable">
        <thead><tr>
          <th>Source</th><th>Type</th><th>Status</th><th>Circuit</th>
          <th>Availability</th><th>Last run</th><th>Actions</th>
        </tr></thead>
        <tbody>
          {pageItems.map(s=>
            <tr key={s.id}>
              <td>
                <b>{s.source_name}</b>
                {s.official_url && <><br/><a className="linkbtn" target="_blank" rel="noreferrer" href={safeHref(s.official_url)}>Official URL</a></>}
                {s.organization && <><br/><span className="muted">{s.organization}{s.category?` · ${s.category}`:""}</span></>}
              </td>
              <td><span className="pill">{s.collector_type}</span></td>
              <td><span className={`badge badge-${s.status}`}>{s.status}</span></td>
              <td><span className={`badge badge-${s.circuit_state}`}>{s.circuit_state}</span></td>
              <td>{s.availability_pct!=null?`${s.availability_pct}%`:"—"}</td>
              <td>{s.last_run_at?new Date(s.last_run_at).toLocaleString():"Never"}</td>
              <td>
                <div className="actions">
                  <button className="btn" onClick={()=>runNow(s)}>Run now</button>
                  {s.status!=="active" && <button className="btn secondary" onClick={()=>setStatus(s,"active")}>Activate</button>}
                  {s.status==="active" && <button className="btn secondary" onClick={()=>setStatus(s,"paused")}>Pause</button>}
                  {s.status!=="disabled" && <button className="btn secondary" onClick={()=>setStatus(s,"disabled")}>Disable</button>}
                  <button className="btn secondary" onClick={()=>openDetail(s)}>Details</button>
                </div>
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="pagination">
        <button className="btn secondary" disabled={page<=1} onClick={()=>setPage(p=>p-1)}>Previous</button>
        <span>Page {page} of {pageCount}</span>
        <button className="btn secondary" disabled={page>=pageCount} onClick={()=>setPage(p=>p+1)}>Next</button>
      </div>
    </>}

    {selected && <div className="section">
      <h2>{selected.source_name} — health, runs & logs</h2>
      {detailLoading && <p className="loading">Loading details…</p>}
      {!detailLoading && health && <div className="jobmeta">
        <span>Status<b>{health.status}</b></span>
        <span>Circuit state<b>{health.circuit_state}</b></span>
        <span>Availability<b>{health.availability_pct!=null?`${health.availability_pct}%`:"—"}</b></span>
        <span>Last latency<b>{health.last_latency_ms!=null?`${health.last_latency_ms}ms`:"—"}</b></span>
        <span>Retry count (last run)<b>{health.retry_count}</b></span>
        <span>Consecutive failures<b>{health.consecutive_failures}</b></span>
        <span>Last success<b>{health.last_success_at?new Date(health.last_success_at).toLocaleString():"Never"}</b></span>
        <span>Last failure<b>{health.last_failure_at?new Date(health.last_failure_at).toLocaleString():"Never"}</b></span>
      </div>}

      {!detailLoading && <>
        <h3>Recent runs</h3>
        <div className="jobs">
          {runs.map((r:any)=>
            <div className="card" key={r.id}>
              <b>{r.status}</b>
              <p className="muted">{new Date(r.started_at).toLocaleString()}{r.finished_at?` → ${new Date(r.finished_at).toLocaleString()}`:""}</p>
              <p>Discovered {r.discovered} · Created {r.created} · Skipped {r.skipped}</p>
              {r.error_message && <p className="error">{r.error_message}</p>}
            </div>
          )}
          {runs.length===0 && <p className="empty">No runs yet.</p>}
        </div>

        <h3>Structured logs</h3>
        <div className="loglines">
          {logs.map((l:any)=>
            <div key={l.id} className={`lvl-${l.level}`}>
              [{new Date(l.created_at).toLocaleTimeString()}] {l.level.toUpperCase()} — {l.message}
            </div>
          )}
          {logs.length===0 && <div className="muted">No log entries yet.</div>}
        </div>
      </>}
    </div>}
  </main>;
}
