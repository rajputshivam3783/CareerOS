"use client";
import {useState} from "react";
import Link from "next/link";
import {API,formatApiError,storeSession,deviceId} from "@/lib/api";

/** V17.1 — admin/super_admin login only. There is no registration
 * form here on purpose: admin and super_admin accounts are provisioned
 * out-of-band by an existing admin (POST /admin/create-admin-user),
 * never through public self-service registration. */
export default function Page(){
  const[email,setEmail]=useState(""),[password,setPassword]=useState("");
  const[rememberMe,setRememberMe]=useState(false);
  const[msg,setMsg]=useState(""),[busy,setBusy]=useState(false);

  async function go(){
    setMsg("");setBusy(true);
    try{
      const r = await fetch(`${API}/api/v1/auth/admin/login`, {
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({email,password,remember_me:rememberMe,device_id:deviceId(),device_label:"Web browser"}),
      });
      let j:any={};try{j=await r.json()}catch{}
      if(!r.ok)throw new Error(formatApiError(j));
      storeSession(j);
      location.href="/admin";
    }catch(e:any){setMsg(e.message)}finally{setBusy(false)}
  }

  return <main className="container narrow"><div className="card form">
    <span className="eyebrow">Admin console</span>
    <h1>Admin login</h1>
    <input className="field" type="email" placeholder="Admin email" value={email} onChange={e=>setEmail(e.target.value)}/>
    <input className="field" type="password" placeholder="Password" value={password}
      onChange={e=>setPassword(e.target.value)} onKeyDown={e=>{if(e.key==="Enter")go()}}/>
    <label className="muted checkbox-label"><input type="checkbox" checked={rememberMe} onChange={e=>setRememberMe(e.target.checked)}/> Remember me on this device</label>
    <button className="btn" disabled={busy} onClick={go}>{busy?"Please wait…":"Log in"}</button>
    {msg&&<p className="error">{msg}</p>}
    <hr/>
    <p className="muted">Admin and super admin accounts are created by an existing administrator — there's no public sign-up here.</p>
    <Link href="/login">Candidate login</Link>
  </div></main>
}
