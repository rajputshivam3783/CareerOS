"use client";
import {useState} from "react";
import Link from "next/link";
import {API,formatApiError,storeSession,deviceId} from "@/lib/api";

export default function Page(){
  const[register,setRegister]=useState(false),[verify,setVerify]=useState(false),[reset,setReset]=useState(false);
  const[name,setName]=useState(""),[email,setEmail]=useState(""),[phone,setPhone]=useState("");
  const[password,setPassword]=useState(""),[password2,setPassword2]=useState("");
  const[rememberMe,setRememberMe]=useState(false);
  const[code,setCode]=useState(""),[msg,setMsg]=useState(""),[busy,setBusy]=useState(false);

  async function post(path:string,body:any){
    const r=await fetch(`${API}${path}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    let j:any={};try{j=await r.json()}catch{}
    if(!r.ok)throw new Error(formatApiError(j,"Request failed"));return j
  }
  async function submit(){
    setMsg("");setBusy(true);
    try{
      if(register){
        await post("/auth/candidate/register",{email,password,password_confirm:password2,full_name:name,phone:phone||undefined});
        setVerify(true);setMsg("Verification code sent. Check your email.")
      } else {
        const j=await post("/auth/candidate/login",{email,password,remember_me:rememberMe,device_id:deviceId(),device_label:"Web browser"});
        storeSession(j);location.href="/dashboard"
      }
    }catch(e:any){setMsg(e.message)}finally{setBusy(false)}
  }
  async function confirm(){
    setBusy(true);
    try{await post("/auth/verify-email",{email,code});setVerify(false);setRegister(false);setMsg("Email verified successfully. You can log in now.")}
    catch(e:any){setMsg(e.message)}finally{setBusy(false)}
  }
  async function startReset(){
    setBusy(true);
    try{await post("/auth/forgot-password",{email});setReset(true);setCode("");setPassword("");setPassword2("");setMsg("If the account exists, a reset code was sent.")}
    catch(e:any){setMsg(e.message)}finally{setBusy(false)}
  }
  async function finishReset(){
    setBusy(true);
    try{await post("/auth/reset-password",{email,code,new_password:password,new_password_confirm:password2});setReset(false);setMsg("Password changed. You can log in now.");setCode("");setPassword("");setPassword2("")}
    catch(e:any){setMsg(e.message)}finally{setBusy(false)}
  }

  return <main className="container narrow"><div className="card form">
    <h1>{reset?"Reset password":verify?"Verify your email":register?"Create candidate account":"Candidate login"}</h1>
    {reset?<>
      <p className="muted">Enter the reset code and choose a new password.</p>
      <input className="field" inputMode="numeric" maxLength={6} placeholder="6-digit reset code" value={code} onChange={e=>setCode(e.target.value)}/>
      <input className="field" type="password" placeholder="New password (12+ characters)" value={password} onChange={e=>setPassword(e.target.value)}/>
      <input className="field" type="password" placeholder="Confirm new password" value={password2} onChange={e=>setPassword2(e.target.value)}/>
      <button className="btn" disabled={busy} onClick={finishReset}>{busy?"Please wait…":"Reset password"}</button>
      <button className="linkbtn" onClick={()=>setReset(false)}>Back to login</button>
    </>:verify?<>
      <p className="muted">Enter the 6-digit code sent to <b>{email}</b>.</p>
      <input className="field" inputMode="numeric" maxLength={6} placeholder="6-digit OTP" value={code} onChange={e=>setCode(e.target.value)}/>
      <button className="btn" disabled={busy} onClick={confirm}>{busy?"Verifying…":"Verify email"}</button>
      <button className="linkbtn" onClick={()=>{setBusy(true);post("/auth/resend-otp",{email}).then(()=>setMsg("New code sent.")).finally(()=>setBusy(false))}}>Resend code</button>
    </>:<>
      {register&&<input className="field" placeholder="Full name" value={name} onChange={e=>setName(e.target.value)}/>}
      <input className="field" type="email" placeholder="Email" value={email} onChange={e=>setEmail(e.target.value)}/>
      {register&&<input className="field" type="tel" placeholder="Phone (optional)" value={phone} onChange={e=>setPhone(e.target.value)}/>}
      <input className="field" type="password" placeholder={register?"Password (12+ characters)":"Password"} value={password} onChange={e=>setPassword(e.target.value)}/>
      {register&&<input className="field" type="password" placeholder="Confirm password" value={password2} onChange={e=>setPassword2(e.target.value)}/>}
      {!register&&<label className="muted checkbox-label"><input type="checkbox" checked={rememberMe} onChange={e=>setRememberMe(e.target.checked)}/> Remember me on this device</label>}
      <button className="btn" disabled={busy} onClick={submit}>{busy?"Please wait…":register?"Register & verify email":"Log in"}</button>
      {!register&&<button className="linkbtn" onClick={startReset}>Forgot password?</button>}
      <button className="linkbtn" onClick={()=>setRegister(!register)}>{register?"Already verified? Log in":"New here? Create account"}</button>
    </>}
    {msg&&<p className={msg.toLowerCase().includes("invalid")||msg.toLowerCase().includes("failed")?"error":"muted"}>{msg}</p>}
    <hr/><p className="muted">Hiring for your company?</p>
    <Link className="btn secondary" href="/recruiter-login">Recruiter login / registration</Link>
  </div></main>
}
