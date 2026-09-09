export const API = "";

function cleanError(raw:string,status:number){
  const text=(raw||"").trim();
  if(/<html|<!doctype/i.test(text)){
    if(status===502||/bad gateway/i.test(text)) return "Gateway Cloudflare temporariamente indisponível (502). O servidor local ou o túnel não respondeu a tempo.";
    return `Resposta HTML inesperada do gateway (HTTP ${status}).`;
  }
  try{const j=JSON.parse(text); return j?.detail||j?.message||text;}catch{}
  return text||`HTTP ${status}`;
}

export async function api<T>(path: string, options?: RequestInit, retries=0): Promise<T> {
  let last:any;
  for(let attempt=0;attempt<=retries;attempt++){
    try{
      const r=await fetch(`${API}${path}`, {credentials:"include",...options});
      const raw=await r.text();
      if(!r.ok){
        const err=new Error(cleanError(raw,r.status));
        (err as any).status=r.status; throw err;
      }
      return (raw?JSON.parse(raw):{}) as T;
    }catch(e:any){
      last=e; const status=e?.status;
      const transient=status===502||status===503||status===504||/Failed to fetch|NetworkError/i.test(String(e?.message||e));
      if(attempt<retries&&transient){await new Promise(r=>setTimeout(r,450*(attempt+1)));continue;}
      throw e;
    }
  }
  throw last;
}
