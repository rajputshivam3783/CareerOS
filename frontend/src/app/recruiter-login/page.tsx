"use client";
import {useState} from "react";
import Link from "next/link";
import {API,formatApiError,storeSession,deviceId} from "@/lib/api";

export default function Page(){
  const[reg,setReg]=useState(false),[verify,setVerify]=useState(false);
  const[name,setName]=useState(""),[email,setEmail]=useState("");
  const[companyName,setCompanyName]=useState(""),[companyEmail,setCompanyEmail]=useState(""),[companyWebsite,setCompanyWebsite]=useState("");
  const[password,setPassword]=useState(""),[password2,setPassword2]=useState("");
  const[rememberMe,setRememberMe]=useState(false);
  const[code,setCode]=useState(""),[msg,setMsg]=useState(""),[busy,setBusy]=useState(false);

  async function post(path:string,b:any){
    const r=await fetch(`${API}${path}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});
    let j:any={};try{j=await r.json()}catch{}
    if(!r.ok)throw new Error(formatApiError(j));return j
  }
  async function go(){
    setMsg("");setBusy(true);
    try{
      if(reg){
        await post("/auth/recruiter/register",{
          email,password,password_confirm:password2,full_name:name,
          company_name:companyName,company_email:companyEmail,company_website:companyWebsite||undefined,
        });
        setVerify(true);setMsg("Verification code sent.")
      } else {
        const j=await post("/auth/recruiter/login",{email,password,remember_me:rememberMe,device_id:deviceId(),device_label:"Web browser"});
        storeSession(j);location.href="/recruiter"
      }
    }catch(e:any){setMsg(e.message)}finally{setBusy(false)}
  }
  async function confirm(){
    setBusy(true);
    try{await post("/auth/verify-email",{email,code});setVerify(false);setReg(false);setMsg("Email verified. Your recruiter account now requires admin approval before login.")}
    catch(e:any){setMsg(e.message)}finally{setBusy(false)}
  }

  return <main className="container narrow"><div className="card form">
    <span className="eyebrow">Employer portal</span>
    <h1>{verify?"Verify recruiter email":reg?"Recruiter registration":"Recruiter login"}</h1>
    {verify?<>
      <input className="field" placeholder="6-digit OTP" maxLength={6} value={code} onChange={e=>setCode(e.target.value)}/>
      <button className="btn" disabled={busy} onClick={confirm}>{busy?"Verifying…":"Verify email"}</button>
    </>:<>
      {reg&&<input className="field" placeholder="Your name" value={name} onChange={e=>setName(e.target.value)}/>}
      <input className="field" type="email" placeholder="Work email" value={email} onChange={e=>setEmail(e.target.value)}/>
      {reg&&<input className="field" placeholder="Company name" value={companyName} onChange={e=>setCompanyName(e.target.value)}/>}
      {reg&&<input className="field" type="email" placeholder="Company email" value={companyEmail} onChange={e=>setCompanyEmail(e.target.value)}/>}
      {reg&&<input className="field" placeholder="Company website (optional)" value={companyWebsite} onChange={e=>setCompanyWebsite(e.target.value)}/>}
      <input className="field" type="password" placeholder={reg?"Password (12+ characters)":"Password"} value={password} onChange={e=>setPassword(e.target.value)}/>
      {reg&&<input className="field" type="password" placeholder="Confirm password" value={password2} onChange={e=>setPassword2(e.target.value)}/>}
      {!reg&&<label className="muted checkbox-label"><input type="checkbox" checked={rememberMe} onChange={e=>setRememberMe(e.target.checked)}/> Remember me on this device</label>}
      <button className="btn" disabled={busy} onClick={go}>{busy?"Please wait…":reg?"Register recruiter":"Recruiter login"}</button>
      <button className="linkbtn" onClick={()=>setReg(!reg)}>{reg?"Already approved? Login":"Register as recruiter"}</button>
    </>}
    {msg&&<p className="muted">{msg}</p>}
    <Link href="/login">Candidate login</Link>
  </div></main>
}
