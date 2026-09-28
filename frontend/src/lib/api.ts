export const API=process.env.NEXT_PUBLIC_API_URL||"http://127.0.0.1:8000/api/v1";
export function token(){return typeof window!=="undefined"?localStorage.getItem("careeros_token"):null}
export function refreshToken(){return typeof window!=="undefined"?localStorage.getItem("careeros_refresh_token"):null}
export function currentRole(){return typeof window!=="undefined"?localStorage.getItem("careeros_role"):null}

// V17.1 — a login/refresh response always carries this shape now
// (access_token/refresh_token/role/user), so every call site that
// stores a session can go through one helper instead of repeating
// three localStorage.setItem calls.
export function storeSession(payload:{access_token:string,refresh_token?:string,role?:string}){
  if (typeof window==="undefined") return;
  localStorage.setItem("careeros_token", payload.access_token);
  if (payload.refresh_token) localStorage.setItem("careeros_refresh_token", payload.refresh_token);
  if (payload.role) localStorage.setItem("careeros_role", payload.role);
}

export function clearSession(){
  if (typeof window==="undefined") return;
  localStorage.removeItem("careeros_token");
  localStorage.removeItem("careeros_refresh_token");
  localStorage.removeItem("careeros_role");
}

// A device id is generated once per browser and reused for every
// login, so the backend's session list ("Logged-in devices") shows
// one stable entry per browser rather than a new one each login.
export function deviceId(){
  if (typeof window==="undefined") return undefined;
  let id = localStorage.getItem("careeros_device_id");
  if (!id) { id = crypto.randomUUID(); localStorage.setItem("careeros_device_id", id); }
  return id;
}

/** Best-effort logout: revokes the refresh token server-side, then
 * always clears local storage even if the network call fails. */
export async function logout(){
  const rt = refreshToken();
  try{ await api("/auth/logout", {method:"POST", body: JSON.stringify({refresh_token: rt})}); }catch{}
  clearSession();
}

export function formatApiError(payload: unknown, fallback="Request failed"): string {
  if (typeof payload === "string") return payload;
  if (!payload || typeof payload !== "object") return fallback;
  const obj=payload as Record<string,unknown>;
  if (typeof obj.detail === "string") return obj.detail;
  const candidates = Array.isArray(obj.detail) ? obj.detail : Array.isArray(obj.errors) ? obj.errors : [];
  if (candidates.length) {
    return candidates.map((item:unknown)=>{
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        const e=item as Record<string,unknown>;
        const loc=Array.isArray(e.loc)?e.loc.filter(x=>x!=="body").join("."):"";
        const msg=typeof e.msg==="string"?e.msg:"Invalid value";
        return loc?`${loc}: ${msg}`:msg;
      }
      return "Invalid value";
    }).join("; ");
  }
  if (typeof obj.message === "string") return obj.message;
  return fallback;
}

async function _rawFetch(path:string, options:RequestInit={}){
  const h=new Headers(options.headers);
  if (!(options.body instanceof FormData)) h.set('Content-Type','application/json');
  const t=token();if(t)h.set('Authorization',`Bearer ${t}`);
  return fetch(`${API}${path}`,{...options,headers:h});
}

export async function api(path:string,options:RequestInit={}){
  let r=await _rawFetch(path,options);
  // V17.1 — access tokens are short-lived (15 min); on a 401, try
  // exactly once to refresh silently and replay the original request
  // before giving up, so a valid session doesn't force a full re-login
  // just because the access token happened to expire mid-session.
  if (r.status===401 && refreshToken() && !path.startsWith("/auth/refresh") && !path.startsWith("/auth/login")){
    try{
      const rr=await fetch(`${API}/auth/refresh`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({refresh_token:refreshToken()})});
      if (rr.ok){
        const j=await rr.json();
        storeSession(j);
        r=await _rawFetch(path,options);
      } else {
        clearSession();
      }
    }catch{/* network error refreshing — fall through with the original 401 */}
  }
  if(!r.ok){let payload:unknown=null;try{payload=await r.json()}catch{}throw new Error(formatApiError(payload,`Request failed (${r.status})`))}
  if(r.status===204)return null;return r.json();
}

/** Downloads a file (e.g. a CSV export) from an authenticated endpoint
 * and saves it via the browser, since a plain <a href> can't carry the
 * Authorization header these recruiter export endpoints require. */
export async function apiDownload(path: string, fallbackFilename: string) {
  const r = await _rawFetch(path);
  if (!r.ok) {
    let payload: unknown = null;
    try { payload = await r.json(); } catch {}
    throw new Error(formatApiError(payload, `Download failed (${r.status})`));
  }
  const disposition = r.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/);
  const filename = match ? match[1] : fallbackFilename;
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
