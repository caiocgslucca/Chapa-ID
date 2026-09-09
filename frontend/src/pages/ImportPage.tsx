import { useRef, useState } from "react";
import { UploadCloud, FileSpreadsheet, CheckCircle2, Clock3, Gauge, XCircle } from "lucide-react";
import { API } from "../api";

function fmtDate(value?: string | null){
  if(!value) return "—";
  try { return new Date(value).toLocaleString("pt-BR"); }
  catch { return value; }
}
function fmtDuration(sec?: number | null){
  if(sec == null) return "—";
  if(sec < 60) return `${sec.toFixed(1)} s`;
  const m = Math.floor(sec/60), s = Math.round(sec%60);
  return `${m} min ${s} s`;
}

export function ImportPage(){
  const input=useRef<HTMLInputElement>(null);
  const [file,setFile]=useState<File>();
  const [job,setJob]=useState<any>();
  const [error,setError]=useState("");

  async function run(){
    if(!file)return;
    setError("");
    setJob({
      status:"uploading", percent:0, message:"Enviando arquivo...",
      started_at:null, finished_at:null, processed:0, total:0,
      new:0, updated:0, errors:0
    });

    try{
      const fd=new FormData(); fd.append("file",file);
      const r=await fetch(`${API}/import/start`,{method:"POST",body:fd});
      if(!r.ok) throw new Error(await r.text());
      const {job_id}=await r.json();

      const poll=async()=>{
        const sr=await fetch(`${API}/import/status/${job_id}`);
        if(!sr.ok) throw new Error(await sr.text());
        const status=await sr.json();
        setJob(status);
        if(status.status==="completed" || status.status==="failed") return;
        setTimeout(poll, 350);
      };
      poll();
    }catch(e:any){
      setError(e?.message || "Falha ao importar.");
      setJob((j:any)=>({...j,status:"failed",message:"Falha na importação."}));
    }
  }

  const busy=job && !["completed","failed"].includes(job.status);
  const pct=Math.max(0,Math.min(100,Number(job?.percent||0)));

  return <div className="import-wrap">
    <div className="import-card">
      <UploadCloud size={40}/>
      <h2>Importar base de produtos</h2>
      <p>Use Excel ou CSV contendo SKU, descrição e endereço.</p>

      <div className="dropzone" onClick={()=>!busy && input.current?.click()}>
        <FileSpreadsheet/>
        <strong>{file?file.name:"Selecionar arquivo"}</strong>
        <small>.xlsx ou .csv</small>
      </div>
      <input ref={input} hidden type="file" accept=".xlsx,.csv"
        onChange={e=>{setFile(e.target.files?.[0]);setJob(undefined);setError("")}}/>

      <button className="primary full" disabled={!file||busy} onClick={run}>
        {busy?"Importando...":"Importar base"}
      </button>
    </div>

    {(job || error) && <div className="import-result professional">
      <div className="result-head">
        {job?.status==="completed" ? <CheckCircle2 size={34}/> :
         job?.status==="failed" ? <XCircle size={34}/> : <Gauge size={34}/>}
        <div>
          <h3>{job?.status==="completed"?"Importação concluída":job?.status==="failed"?"Falha na importação":"Importação em andamento"}</h3>
          <p>{job?.message || error}</p>
        </div>
        <strong className="progress-number">{pct}%</strong>
      </div>

      <div className="progress-track">
        <div className="progress-bar" style={{width:`${pct}%`}}></div>
      </div>
      <div className="progress-meta">
        <span>{Number(job?.processed||0).toLocaleString("pt-BR")} de {Number(job?.total||0).toLocaleString("pt-BR")} linhas</span>
        <span>{pct}%</span>
      </div>

      <div className="metrics compact">
        <div className="metric"><div><small>Novos</small><strong>{job?.new||0}</strong></div></div>
        <div className="metric"><div><small>Atualizados</small><strong>{job?.updated||0}</strong></div></div>
        <div className="metric"><div><small>Erros</small><strong>{job?.errors||0}</strong></div></div>
        <div className="metric"><div><small>Total</small><strong>{job?.total||0}</strong></div></div>
      </div>

      <div className="timing-grid">
        <div><Clock3/><span><small>Início</small><strong>{fmtDate(job?.started_at)}</strong></span></div>
        <div><Clock3/><span><small>Fim</small><strong>{fmtDate(job?.finished_at)}</strong></span></div>
        <div><Gauge/><span><small>Duração</small><strong>{fmtDuration(job?.duration_seconds)}</strong></span></div>
      </div>

      {job?.error && <div className="import-error">{job.error}</div>}
    </div>}
  </div>
}
