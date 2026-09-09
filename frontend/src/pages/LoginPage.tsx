import { useState } from "react";
import { LockKeyhole, ScanLine, ShieldCheck, LogIn } from "lucide-react";
import { API } from "../api";

export function LoginPage({onLogin}:{onLogin:()=>void}){
  const [username,setUsername]=useState("chapaid");
  const [password,setPassword]=useState("");
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");

  async function submit(e:any){
    e.preventDefault();
    setLoading(true); setError("");
    try{
      const r=await fetch(`${API}/auth/login`,{
        method:"POST",
        credentials:"include",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({username,password})
      });
      if(!r.ok){
        const x=await r.json().catch(()=>({detail:"Falha no acesso."}));
        throw new Error(x.detail || "Usuário ou senha inválidos.");
      }
      onLogin();
    }catch(e:any){
      setError(e?.message || "Não foi possível entrar.");
    }finally{
      setLoading(false);
    }
  }

  return <div className="login-screen">
    <div className="login-ambient one"></div>
    <div className="login-ambient two"></div>

    <div className="login-card">
      <div className="login-brand">
        <div className="login-logo"><ScanLine size={27}/></div>
        <div><strong>CHAPA ID</strong><small>Identificação Inteligente de Produtos</small></div>
      </div>

      <div className="login-copy">
        <span className="eyebrow">ACESSO PROTEGIDO</span>
        <h1>Identificação visual, rápida e segura.</h1>
        <p>Entre para acessar a câmera, produtos, histórico e impressão.</p>
      </div>

      <form onSubmit={submit}>
        <label>Usuário
          <div className="login-input"><ShieldCheck/><input autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)}/></div>
        </label>
        <label>Senha
          <div className="login-input"><LockKeyhole/><input autoFocus type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="Digite sua senha"/></div>
        </label>

        {error && <div className="login-error">{error}</div>}

        <button className="primary big full" disabled={loading || !password}>
          <LogIn/> {loading?"Entrando...":"Entrar no CHAPA ID"}
        </button>
      </form>

      <div className="login-security"><ShieldCheck/> Sessão protegida • acesso por HTTPS</div>
    </div>
  </div>
}
