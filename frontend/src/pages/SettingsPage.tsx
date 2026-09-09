import {useEffect,useState} from "react";
import {BrainCircuit,KeyRound,ShieldCheck,Save,Database,SlidersHorizontal,PlugZap,Trash2,ClipboardCheck,CheckCircle2,AlertTriangle,XCircle,Activity,RefreshCw} from "lucide-react";
import {api} from "../api";

export function SettingsPage(){
 const [s,setS]=useState<any>(); const [stats,setStats]=useState<any>(); const [usage,setUsage]=useState<any>(); const [check,setCheck]=useState<any>();
 const [msg,setMsg]=useState(""); const [testing,setTesting]=useState(false); const [checking,setChecking]=useState(false);
 const load=()=>{api<any>("/settings/ai").then(setS);api<any>("/settings/ai/learning-stats").then(setStats);api<any>("/settings/ai/usage-stats").then(setUsage)};
 useEffect(load,[]);
 if(!s)return <div className="card">Carregando configurações...</div>;
 const upd=(k:string,v:any)=>setS({...s,[k]:v});
 async function save(){try{setMsg("Salvando...");await api("/settings/ai",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(s)});setMsg("Configuração salva com segurança.");load()}catch(e:any){setMsg("Falha ao salvar: "+e.message)}}
 async function test(){
  try{
   setTesting(true);setMsg("Iniciando teste seguro no servidor...");
   const start:any=await api("/settings/ai/test/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({provider:s.provider,model:s.model,api_key:s.api_key})},2);
   const job=start.job_id;if(!job)throw new Error("Servidor não retornou o identificador do teste.");
   const deadline=Date.now()+30000;
   while(Date.now()<deadline){
    await new Promise(r=>setTimeout(r,700));
    try{
     const r:any=await api(`/settings/ai/test/status/${job}`,undefined,2);
     if(r.status==="running"){setMsg("Testando diretamente do servidor com o provedor de IA...");continue}
     if(r.status==="done"){
      if(!r.ok)throw new Error(r.message||"O provedor recusou o teste.");
      setMsg(`Conexão aprovada • ${Math.round(r.latency_ms||0)} ms • ${r.provider} / ${r.model}`);
      setS({...s,api_key:"",api_key_configured:true,last_test_ok:true,last_test_message:r.message});
      load();return;
     }
    }catch(e:any){
     if(/Gateway Cloudflare|Failed to fetch|NetworkError/i.test(String(e?.message||e))){setMsg("Túnel oscilou durante a consulta; retomando o status automaticamente...");continue}
     throw e;
    }
   }
   throw new Error("O teste ultrapassou 30 segundos. O sistema não salvou um resultado falso; tente novamente.");
  }catch(e:any){setMsg("Teste não concluído: "+String(e?.message||e))}
  finally{setTesting(false)}
 }
 async function clearKey(){if(!confirm("Remover a chave da API salva neste computador?"))return;await api("/settings/ai/key",{method:"DELETE"});setMsg("Chave removida.");load()}
 async function runCheck(){try{setChecking(true);setCheck(await api<any>("/settings/professional-check",{method:"POST"}))}finally{setChecking(false)}}
 const statusIcon=(x:string)=>x==="pass"?<CheckCircle2/>:x==="warn"?<AlertTriangle/>:<XCircle/>;
 return <div className="settings-grid settings-pro">
  <section className="card settings-hero"><BrainCircuit/><div><h2>V7 — Motor Visual Industrial Pro</h2><p>Fingerprints multi-região, travas físicas, abstenção segura, consenso do scanner e IA externa como auditor dos finalistas.</p></div></section>

  <section className="card settings-card"><h3><ShieldCheck/> Modo de decisão</h3>
   <div className="guard-note"><ShieldCheck/> Auditoria por IA fica <b>automaticamente ativa</b> quando o modo Híbrido/IA estiver selecionado e houver uma chave configurada. Para desligar, selecione <b>Somente Local</b>.</div>
   <label>Modo<select value={s.mode} onChange={e=>upd("mode",e.target.value)}><option value="local">Somente Local</option><option value="hybrid">Híbrido — recomendado</option><option value="ai">IA como auditor obrigatório</option></select></label>
   <label>Provedor<select value={s.provider} onChange={e=>upd("provider",e.target.value)}><option value="gemini">Google Gemini</option><option value="openai">OpenAI</option></select></label>
   <label>Modelo<input value={s.model||""} onChange={e=>upd("model",e.target.value)}/><small>Use um modelo multimodal disponível para sua chave. O teste de conexão valida o modelo antes da operação.</small></label>
   <label><KeyRound size={16}/> Chave da API<input type="password" autoComplete="off" placeholder={s.api_key_configured?"Chave protegida no servidor — deixe vazio para manter":"Cole a chave da API"} value={s.api_key||""} onChange={e=>upd("api_key",e.target.value)}/></label>
   <div className="connection-row"><button className="secondary" onClick={test} disabled={testing}><PlugZap/>{testing?"Testando...":"Testar conexão"}</button>{s.api_key_configured&&<button className="danger-outline" onClick={clearKey}><Trash2/>Remover chave</button>}</div>
   <div className={`provider-status ${s.last_test_ok===true?"ok":s.last_test_ok===false?"bad":"idle"}`}><Activity/><div><b>{s.last_test_ok===true?"Provedor validado":s.last_test_ok===false?"Último teste falhou":"Conexão ainda não testada"}</b><small>{s.last_test_message||"Faça um teste antes de colocar em produção."}</small></div></div>
   <small>O teste é executado em segundo plano no backend. Assim uma oscilação do Quick Tunnel não interrompe a chamada ao Gemini/OpenAI.</small>
  </section>

  <section className="card settings-card"><h3><SlidersHorizontal/> Travas profissionais</h3>
   <label>Confiança local mínima <b>{s.min_local_confidence}%</b><input type="range" min="55" max="98" value={s.min_local_confidence} onChange={e=>upd("min_local_confidence",Number(e.target.value))}/><small>Abaixo deste valor nem a IA pode liberar o produto.</small></label>
   <label>Acionar auditor abaixo de <b>{s.audit_below}%</b><input type="range" min="70" max="99" value={s.audit_below} onChange={e=>upd("audit_below",Number(e.target.value))}/></label>
   <label>Máximo de candidatos<input type="number" min="1" max="5" value={s.max_candidates} onChange={e=>upd("max_candidates",Number(e.target.value))}/></label>
   <label>Timeout da IA (segundos)<input type="number" min="5" max="60" value={s.ai_timeout_seconds||25} onChange={e=>upd("ai_timeout_seconds",Number(e.target.value))}/></label>
   <label className="toggle-line"><span><b>Auditar sempre quando houver empate</b><small>Recomendado para acabamentos visualmente equivalentes.</small></span><input type="checkbox" checked={!!s.require_ai_on_ambiguous} onChange={e=>upd("require_ai_on_ambiguous",e.target.checked)}/></label>
   <div className="guard-note"><ShieldCheck/> A IA nunca recebe candidatos eliminados por conflito físico e nunca pode ultrapassar a confiança da evidência local.</div>
  </section>

  <section className="card settings-card"><h3><Database/> Aprendizado supervisionado</h3>
   <label className="toggle-line"><span><b>Aprender com confirmações</b><small>V7 usa quarentena: somente evidências consistentes entram automaticamente; correções ficam pendentes para não contaminar o reconhecimento.</small></span><input type="checkbox" checked={!!s.learning_enabled} onChange={e=>upd("learning_enabled",e.target.checked)}/></label>
   <div className="learning-stats"><span><b>{stats?.confirmed_photos||0}</b> fotos reais</span><span><b>{stats?.events||0}</b> decisões</span><span><b>{stats?.corrections||0}</b> correções</span><span><b>{usage?.audits||0}</b> auditorias IA</span><span><b>{stats?.quarantine_pending||0}</b> em quarentena</span></div>
   <label>Instruções operacionais<textarea rows={6} value={s.custom_instruction||""} onChange={e=>upd("custom_instruction",e.target.value)} placeholder="Ex.: para MDF branco, exigir iluminação controlada; nunca comparar MDF com sarrafo; em empate de espessura, solicitar confirmação humana..."/><small>Estas instruções orientam o auditor; não substituem as travas técnicas do motor local.</small></label>
  </section>

  <section className="card settings-card readiness-card"><h3><ClipboardCheck/> Check profissional de prontidão</h3><p className="muted">Audita catálogo, cobertura visual, integridade, equivalência visual, quarentena de aprendizado, armazenamento, Cloudflare, IA e ativação do Motor Visual Industrial Pro V7.</p>
   <button className="secondary check-btn" onClick={runCheck} disabled={checking}><RefreshCw className={checking?"spin":""}/>{checking?"Executando auditoria...":"Executar Check Profissional"}</button>
   {check&&<><div className={`readiness-score ${check.overall}`}><strong>{check.score.toFixed(1)}%</strong><span>{check.overall==="ready"?"PRONTO PARA OPERAÇÃO":check.overall==="attention"?"ATENÇÃO NECESSÁRIA":"BLOQUEIOS ENCONTRADOS"}</span><small>{check.blockers} bloqueio(s) • {check.warnings} alerta(s)</small></div>
   <div className="check-list">{check.checks.map((c:any)=><div key={c.key} className={`check-item ${c.status}`}>{statusIcon(c.status)}<div><b>{c.label}</b><small>{c.detail}</small>{c.action&&<em>Ação: {c.action}</em>}</div></div>)}</div></>}
  </section>

  <div className="settings-save"><button className="primary" onClick={save}><Save/> Salvar configurações</button><span>{msg}</span></div>
 </div>
}
