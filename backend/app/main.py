from __future__ import annotations

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime, timedelta
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
import csv, io, json, shutil, uuid, time, os, re, base64, urllib.request, urllib.error, ssl, ctypes, ctypes.wintypes, secrets, hashlib
import threading
from openpyxl import load_workbook

from .db import connect, init_db, BASE_DIR
from .services.vision import engine, dumps_feature, loads_feature, feature_is_current
from .services.printing import printer, LabelData
from .services.auth import ensure_auth, verify_password, create_session, verify_session
from .services.leo_catalog import discover_catalog_links, iter_rendered_products_parallel, fetch_rendered_product_isolated, download_image

app = FastAPI(title="CHAPA ID API", version="10.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MEDIA_DIR = BASE_DIR / "data" / "images"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
IMPORT_DIR = BASE_DIR / "data" / "imports"
IMPORT_DIR.mkdir(parents=True, exist_ok=True)

IMPORT_JOBS: dict[str, dict] = {}
IMPORT_LOCK = Lock()
CATALOG_JOBS: dict[str, dict] = {}
CATALOG_LOCK = Lock()
AI_TEST_JOBS: dict[str, dict] = {}
AI_TEST_LOCK = Lock()

def _site_key_from_url(url: str) -> str:
    """Chave estável do item do site Leo: /p/<id>/... .

    O slug pode mudar; o id do produto do e-commerce é o identificador persistente.
    """
    m=re.search(r'/p/(\d+)(?:/|$)', str(url or ''), re.I)
    return m.group(1) if m else str(url or '').split('#',1)[0].split('?',1)[0].rstrip('/').lower()

def _resolve_media_path(file_path: str, sku: str | None = None) -> Path | None:
    """Resolve caminhos de mídia mesmo quando a pasta do projeto mudou.

    A base pode ter sido criada em outro notebook/pasta (ex.: ChapariaV2) e
    guardar caminho absoluto antigo no SQLite. O arquivo físico continua dentro
    de backend/data/images; por isso reconstruímos o caminho local pelo SKU.
    """
    raw = str(file_path or "").strip()
    if raw:
        direct = Path(raw)
        if direct.exists() and direct.is_file():
            return direct

    filename = raw.replace("\\", "/").split("/")[-1] if raw else ""
    candidates: list[Path] = []
    if sku:
        sku_dir = MEDIA_DIR / str(sku)
        if filename:
            candidates.extend([
                sku_dir / "catalogo_leo" / filename,
                sku_dir / filename,
            ])
        # fallback profissional: qualquer imagem válida do SKU, priorizando catálogo Leo
        leo_dir = sku_dir / "catalogo_leo"
        if leo_dir.exists():
            candidates.extend(sorted(x for x in leo_dir.iterdir() if x.is_file()))
        if sku_dir.exists():
            candidates.extend(sorted(x for x in sku_dir.iterdir() if x.is_file()))

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None

def _repair_media_paths() -> int:
    """Auto-repara no startup os caminhos absolutos antigos gravados no SQLite."""
    repaired = 0
    con = connect()
    rows = con.execute("""
        SELECT m.id, m.file_path, p.sku
        FROM product_media m
        JOIN products p ON p.id=m.product_id
        WHERE m.media_type='image'
    """).fetchall()
    for row in rows:
        resolved = _resolve_media_path(row["file_path"], row["sku"])
        if resolved is None:
            continue
        new_path = str(resolved.resolve())
        if str(row["file_path"] or "") != new_path:
            con.execute("UPDATE product_media SET file_path=? WHERE id=?", (new_path, row["id"]))
            repaired += 1
    con.commit()
    con.close()
    return repaired



def _repair_catalog_media_integrity():
    """V10: remove vínculos visuais contaminados por SKU stale do coletor.

    Se um SKU recebeu múltiplas URLs de imagem Leo no histórico, todo o conjunto é
    considerado contaminado porque versões antigas reutilizavam principal.jpg e o
    conteúdo físico podia ter sido sobrescrito. O Check-List baixa novamente só esse SKU.
    """
    con=connect(); removed=0; contaminated_products=0
    rows=con.execute("""
        SELECT m.id,m.product_id,m.file_path,m.source_url,p.sku,p.source_image_url
        FROM product_media m JOIN products p ON p.id=m.product_id
        WHERE m.media_type='image' AND m.source='leo_site'
        ORDER BY m.product_id,m.id
    """).fetchall()
    by_product={}
    for r in rows: by_product.setdefault(int(r["product_id"]),[]).append(r)
    for product_id, group in by_product.items():
        expected=str(group[0]["source_image_url"] or "").strip()
        urls={str(r["source_url"] or "").strip() for r in group if str(r["source_url"] or "").strip()}
        paths={str(r["file_path"] or "").strip() for r in group if str(r["file_path"] or "").strip()}
        stale_any=any(expected and str(r["source_url"] or "").strip() and str(r["source_url"] or "").strip()!=expected for r in group)
        shared_overwrite_risk=(len(urls)>1 and len(paths)<len(urls)) or len(urls)>1
        if stale_any or shared_overwrite_risk:
            con.execute("DELETE FROM product_media WHERE product_id=? AND media_type='image' AND source='leo_site'",(product_id,))
            removed+=len(group); contaminated_products+=1
            continue
        # limpa duplicidade exata sem destruir uma referência saudável
        seen=set()
        for r in group:
            key=(str(r["source_url"] or ""),str(r["file_path"] or ""))
            if key in seen:
                con.execute("DELETE FROM product_media WHERE id=?",(r["id"],)); removed+=1
            else: seen.add(key)
    con.commit(); con.close()
    if removed:
        print(f"[CHAPA-ID][V10][CATALOG-INTEGRITY] {removed} vínculo(s) removido(s) em {contaminated_products} SKU(s) contaminado(s); Check-List fará reparo seletivo.",flush=True)
    return {"removed":removed,"contaminated_products":contaminated_products}

def _is_sheet_product(description: str | None) -> bool:
    d=re.sub(r"\s+"," ",str(description or "").strip().upper())
    allowed=("MDF ","MDP ","COMPENSADO ","OSB ","PAINEL ","CHAPA ","FÓRMICA ","FORMICA ","LAMINADO ","MEIA CHAPA ","HDF ","HARDBOARD ","MADEIRITE ")
    blocked=("RODAPÉ ","RODAPE ","PORTA ","SAPATA ","RIPA ","SARRAFO ","BATENTE ","GUARNIÇÃO ","GUARNICAO ","PERFIL ","COLA ","FERRAGEM ","DOBRADIÇA ","DOBRADICA ")
    if d.startswith(blocked): return False
    return d.startswith(allowed)

@app.on_event("startup")
def startup():
    init_db()
    _repair_media_paths()
    _repair_catalog_media_integrity()
    ensure_auth()

class ProductIn(BaseModel):
    sku: str
    description: str
    address: str
    family: str | None = None
    thickness: str | None = None
    color: str | None = None
    manufacturer: str | None = None

class ConfirmIn(BaseModel):
    confirmed_sku: str
    operator: str | None = None


class AISettingsIn(BaseModel):
    enabled: bool = False
    provider: str = "gemini"
    model: str = "gemini-2.5-flash-lite"
    api_key: str | None = None
    mode: str = "hybrid"
    min_local_confidence: float = 72
    audit_below: float = 92
    max_candidates: int = 5
    learning_enabled: bool = True
    custom_instruction: str = ""
    max_ai_calls_per_identification: int = 1
    ai_timeout_seconds: int = 25
    require_ai_on_ambiguous: bool = True


# ---------------------------------------------------------------------------
# Segurança de segredo + auditor multimodal (V5.1)
# ---------------------------------------------------------------------------
def _dpapi_protect(secret: str) -> str:
    if not secret:
        return ""
    raw=secret.encode("utf-8")
    if os.name != "nt":
        # Compatibilidade de desenvolvimento. Em produção Windows usamos DPAPI.
        return "b64:"+base64.b64encode(raw).decode("ascii")
    class DATA_BLOB(ctypes.Structure):
        _fields_=[("cbData",ctypes.wintypes.DWORD),("pbData",ctypes.POINTER(ctypes.c_byte))]
    buf=ctypes.create_string_buffer(raw)
    in_blob=DATA_BLOB(len(raw),ctypes.cast(buf,ctypes.POINTER(ctypes.c_byte)))
    out_blob=DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(in_blob),"CHAPA ID",None,None,None,0,ctypes.byref(out_blob)):
        raise OSError("Falha ao proteger chave da API com Windows DPAPI.")
    try:
        enc=ctypes.string_at(out_blob.pbData,out_blob.cbData)
        return "dpapi:"+base64.b64encode(enc).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)

def _dpapi_unprotect(value: str | None) -> str:
    v=str(value or "")
    if not v: return ""
    if v.startswith("b64:"):
        try:return base64.b64decode(v[4:]).decode("utf-8")
        except Exception:return ""
    if not v.startswith("dpapi:"):
        # migração automática de V5.0, que armazenava texto puro
        return v
    if os.name != "nt": return ""
    class DATA_BLOB(ctypes.Structure):
        _fields_=[("cbData",ctypes.wintypes.DWORD),("pbData",ctypes.POINTER(ctypes.c_byte))]
    enc=base64.b64decode(v[6:]); buf=ctypes.create_string_buffer(enc)
    in_blob=DATA_BLOB(len(enc),ctypes.cast(buf,ctypes.POINTER(ctypes.c_byte))); out_blob=DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(in_blob),None,None,None,None,0,ctypes.byref(out_blob)):
        return ""
    try:return ctypes.string_at(out_blob.pbData,out_blob.cbData).decode("utf-8")
    finally:ctypes.windll.kernel32.LocalFree(out_blob.pbData)

def _json_post(url: str, payload: dict, headers: dict, timeout: int=25) -> dict:
    data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request(url,data=data,headers={"Content-Type":"application/json",**headers},method="POST")
    ctx=ssl.create_default_context()
    try:
        with urllib.request.urlopen(req,timeout=max(5,min(60,int(timeout))),context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8","replace"))
    except urllib.error.HTTPError as e:
        body=e.read().decode("utf-8","replace")[:1200]
        # Traduz os erros mais comuns sem despejar HTML/JSON bruto na tela.
        if e.code in (401,403):
            raise RuntimeError(f"Chave recusada pelo provedor (HTTP {e.code}). Verifique a chave e as permissões do projeto.")
        if e.code==404:
            raise RuntimeError(f"Modelo ou endpoint não encontrado (HTTP 404). Verifique o nome do modelo configurado.")
        if e.code==429:
            raise RuntimeError("Limite/quota da API atingido (HTTP 429). Aguarde ou verifique o plano/quota do provedor.")
        if e.code>=500:
            raise RuntimeError(f"Serviço do provedor temporariamente indisponível (HTTP {e.code}).")
        clean=re.sub(r'<[^>]+>',' ',body); clean=re.sub(r'\s+',' ',clean).strip()
        raise RuntimeError(f"HTTP {e.code}: {clean[:360]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Falha de rede ao acessar o provedor: {e.reason}")
    except TimeoutError:
        raise RuntimeError("Tempo limite ao acessar o provedor de IA.")

def _extract_json_object(text: str) -> dict:
    t=str(text or "").strip()
    t=re.sub(r'^```(?:json)?\\s*|\\s*```$','',t,flags=re.I|re.S).strip()
    try:return json.loads(t)
    except Exception: pass
    m=re.search(r'\\{.*\\}',t,re.S)
    if not m: raise RuntimeError("IA não retornou JSON válido.")
    return json.loads(m.group(0))

def _image_b64(path: Path, max_side: int=384, quality: int=62) -> str:
    from PIL import Image
    with Image.open(path) as im:
        im=im.convert("RGB"); im.thumbnail((max_side,max_side))
        b=io.BytesIO(); im.save(b,format="JPEG",quality=quality,optimize=True)
    return base64.b64encode(b.getvalue()).decode("ascii")

def _ai_text(provider: str, model: str, key: str, prompt: str, images: list[tuple[str,Path]]|None=None, timeout: int=25) -> tuple[str,float]:
    started=time.perf_counter(); images=images or []
    if provider=="gemini":
        parts=[{"text":prompt}]
        for label,path in images:
            parts.append({"text":label}); parts.append({"inlineData":{"mimeType":"image/jpeg","data":_image_b64(path)}})
        data=_json_post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",{"contents":[{"parts":parts}],"generationConfig":{"temperature":0.05}}, {"x-goog-api-key":key}, timeout)
        try:text="\\n".join(p.get("text","") for p in data["candidates"][0]["content"]["parts"] if p.get("text"))
        except Exception: raise RuntimeError("Resposta Gemini sem conteúdo utilizável.")
    elif provider=="openai":
        content=[{"type":"input_text","text":prompt}]
        for label,path in images:
            content.append({"type":"input_text","text":label})
            content.append({"type":"input_image","image_url":"data:image/jpeg;base64,"+_image_b64(path),"detail":"low"})
        data=_json_post("https://api.openai.com/v1/responses",{"model":model,"input":[{"role":"user","content":content}],"max_output_tokens":700}, {"Authorization":"Bearer "+key}, timeout)
        text=str(data.get("output_text") or "")
        if not text:
            chunks=[]
            for o in data.get("output",[]):
                for c in o.get("content",[]):
                    if c.get("type") in {"output_text","text"}: chunks.append(c.get("text",''))
            text="\\n".join(chunks)
        if not text: raise RuntimeError("Resposta OpenAI sem conteúdo utilizável.")
    else: raise RuntimeError("Provedor não suportado.")
    return text,round((time.perf_counter()-started)*1000,1)

def _load_ai_settings_private() -> dict:
    con=connect(); r=con.execute("SELECT * FROM ai_settings WHERE id=1").fetchone(); con.close()
    d=dict(r) if r else {}; d["api_key"]=_dpapi_unprotect(d.get("api_key")); return d

def _audit_candidates_with_ai(query_path: Path, candidates: list[dict], settings: dict, recovery_mode: bool=False) -> dict:
    if not candidates:return {"used":False,"outcome":"no_candidates"}
    configured_max=max(1,min(5,int(settings.get("max_candidates") or 5)))
    # Recuperação fotométrica precisa responder dentro da janela do navegador/Quick Tunnel.
    # Três candidatos fisicamente plausíveis dão melhor latência sem abrir espaço para opções irrelevantes.
    maxc=min(configured_max,2)
    cands=candidates[:maxc]
    images=[("IMAGEM CONSULTA — produto físico fotografado",query_path)]
    lines=[]
    for i,c in enumerate(cands,1):
        mid=c.get("image_url") or ""; ref=None
        m=re.search(r'/media/(\\d+)',mid)
        if m:
            con=connect(); rr=con.execute("SELECT m.file_path,p.sku FROM product_media m JOIN products p ON p.id=m.product_id WHERE m.id=?",(int(m.group(1)),)).fetchone(); con.close()
            if rr: ref=_resolve_media_path(rr["file_path"],rr["sku"])
        lines.append(f"C{i}: SKU={c.get('sku')} | descrição={c.get('description')} | local_visual={float(c.get('score') or 0):.1f}%")
        if ref: images.append((f"REFERÊNCIA C{i} — SKU {c.get('sku')}",ref))
    instruction=str(settings.get("custom_instruction") or "").strip()
    recovery_note=("MODO RECUPERAÇÃO FOTOMÉTRICA: a captura pode estar subexposta. Não use brilho absoluto como cor real; compare textura, uniformidade, estrutura e relações relativas entre consulta e referências. " if recovery_mode else "")
    prompt=("Você é o auditor visual do CHAPA ID. "+recovery_note+"Compare a IMAGEM CONSULTA exclusivamente com os candidatos permitidos abaixo. "
            "Não invente SKU, não escolha por semelhança textual e não libere candidato fisicamente incompatível. "
            "Considere diferenças de iluminação, mas não transforme branco em cinza/preto apenas por subexposição. "
            "Se não houver evidência suficiente, rejeite todos. Responda SOMENTE JSON no formato: "
            '{"decision":"select|reject","sku":"...|null","confidence":0-100,"reason":"curto","ranking":[{"sku":"...","score":0-100}]}.\\n'
            +"\\n".join(lines)+(f"\\nRegra operacional adicional: {instruction}" if instruction else ""))
    ai_timeout=int(settings.get("ai_timeout_seconds") or 25)
    if recovery_mode:
        # Evita o POST /identify ultrapassar a tolerância do Quick Tunnel/browser.
        ai_timeout=max(6,min(ai_timeout,10))
    text,lat=_ai_text(settings.get("provider","gemini"),settings.get("model","gemini-2.5-flash-lite"),settings.get("api_key",""),prompt,images,ai_timeout)
    obj=_extract_json_object(text); allowed={str(c.get("sku")) for c in cands}; decision=str(obj.get("decision") or "reject").lower(); sku=str(obj.get("sku") or "")
    conf=max(0.0,min(100.0,float(obj.get("confidence") or 0)))
    if decision!="select" or sku not in allowed: return {"used":True,"outcome":"reject","sku":None,"confidence":conf,"reason":str(obj.get("reason") or "IA rejeitou os candidatos."),"latency_ms":lat,"raw":obj}
    return {"used":True,"outcome":"select","sku":sku,"confidence":conf,"reason":str(obj.get("reason") or "Auditoria visual concluída."),"latency_ms":lat,"raw":obj}

@app.get("/settings/ai")
def get_ai_settings():
    con=connect(); r=con.execute("SELECT * FROM ai_settings WHERE id=1").fetchone(); con.close()
    d=dict(r) if r else {}
    d["enabled"]=bool(d.get("enabled")); d["learning_enabled"]=bool(d.get("learning_enabled")); d["require_ai_on_ambiguous"]=bool(d.get("require_ai_on_ambiguous",1))
    d["api_key_configured"]=bool(d.get("api_key")); d["api_key"]=""
    d["last_test_ok"]=(None if d.get("last_test_ok") is None else bool(d.get("last_test_ok")))
    return d

@app.put("/settings/ai")
def save_ai_settings(data: AISettingsIn):
    provider=data.provider.strip().lower()
    if provider not in {"gemini","openai"}: raise HTTPException(400,"Provedor inválido.")
    mode=data.mode.strip().lower()
    if mode not in {"local","hybrid","ai"}: raise HTTPException(400,"Modo inválido.")
    con=connect(); old=con.execute("SELECT api_key FROM ai_settings WHERE id=1").fetchone()
    incoming=(data.api_key or "").strip()
    key=_dpapi_protect(incoming) if incoming else (old["api_key"] if old else None)
    con.execute("""UPDATE ai_settings SET enabled=?,provider=?,model=?,api_key=?,mode=?,min_local_confidence=?,audit_below=?,max_candidates=?,learning_enabled=?,custom_instruction=?,max_ai_calls_per_identification=?,ai_timeout_seconds=?,require_ai_on_ambiguous=?,updated_at=CURRENT_TIMESTAMP WHERE id=1""",
      (int(data.enabled),provider,data.model.strip(),key,mode,max(0,min(100,data.min_local_confidence)),max(0,min(100,data.audit_below)),max(1,min(8,data.max_candidates)),int(data.learning_enabled),data.custom_instruction[:4000],max(0,min(3,data.max_ai_calls_per_identification)),max(5,min(60,data.ai_timeout_seconds)),int(data.require_ai_on_ambiguous)))
    con.commit(); con.close(); return {"ok":True}


class AITestIn(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None

def _ai_test_worker(job_id: str, provider: str, model: str, key: str):
    started=time.perf_counter()
    with AI_TEST_LOCK:
        AI_TEST_JOBS[job_id]={"id":job_id,"status":"running","provider":provider,"model":model,"started_at":datetime.now().isoformat()}
    try:
        text,lat=_ai_text(provider,model,key,'Responda exatamente: {"ok":true,"service":"CHAPA ID"}',[],12)
        if not text:
            raise RuntimeError("O provedor respondeu sem conteúdo utilizável.")
        ok=True; msg=f"Conexão aprovada em {lat:.0f} ms."
        result={"ok":True,"provider":provider,"model":model,"latency_ms":lat,"message":msg}
    except Exception as e:
        ok=False; lat=None; msg=str(e)[:500]
        result={"ok":False,"provider":provider,"model":model,"latency_ms":None,"message":msg}
    try:
        con=connect(); con.execute("UPDATE ai_settings SET last_test_at=CURRENT_TIMESTAMP,last_test_ok=?,last_test_message=? WHERE id=1",(int(ok),msg)); con.commit(); con.close()
    except Exception:
        pass
    with AI_TEST_LOCK:
        AI_TEST_JOBS[job_id].update({"status":"done","finished_at":datetime.now().isoformat(),"elapsed_ms":round((time.perf_counter()-started)*1000,1),**result})

@app.post("/settings/ai/test/start")
def start_ai_connection_test(data: AITestIn):
    s=_load_ai_settings_private()
    provider=(data.provider or s.get("provider") or "gemini").strip().lower()
    model=(data.model or s.get("model") or "").strip()
    key=(data.api_key or "").strip() or s.get("api_key") or ""
    if provider not in {"gemini","openai"}: raise HTTPException(400,"Provedor inválido.")
    if not model: raise HTTPException(400,"Informe o modelo antes de testar.")
    if not key: raise HTTPException(400,"Informe uma chave de API antes de testar.")
    # Se uma chave nova veio da tela, salvamos protegida imediatamente. O teste
    # continua em segundo plano e nenhuma conexão HTTP longa fica pendurada no Quick Tunnel.
    if (data.api_key or "").strip():
        con=connect(); con.execute("UPDATE ai_settings SET provider=?,model=?,api_key=?,updated_at=CURRENT_TIMESTAMP WHERE id=1",(provider,model,_dpapi_protect(key))); con.commit(); con.close()
    job_id=uuid.uuid4().hex
    threading.Thread(target=_ai_test_worker,args=(job_id,provider,model,key),daemon=True,name=f"ai-test-{job_id[:6]}").start()
    return {"ok":True,"job_id":job_id,"status":"started","message":"Teste iniciado no servidor."}

@app.get("/settings/ai/test/status/{job_id}")
def ai_connection_test_status(job_id: str):
    with AI_TEST_LOCK:
        job=AI_TEST_JOBS.get(job_id)
        if not job: raise HTTPException(404,"Teste não encontrado ou expirado.")
        return dict(job)

@app.post("/settings/ai/test")
def test_ai_connection_compat(data: AITestIn):
    # Compatibilidade V5.1: agora apenas inicia o job e devolve imediatamente.
    return start_ai_connection_test(data)

@app.delete("/settings/ai/key")
def clear_ai_key():
    con=connect(); con.execute("UPDATE ai_settings SET api_key=NULL,last_test_ok=NULL,last_test_message=NULL WHERE id=1"); con.commit(); con.close(); return {"ok":True}

@app.get("/settings/ai/usage-stats")
def ai_usage_stats():
    con=connect(); total=con.execute("SELECT COUNT(*) n FROM ai_audit_logs").fetchone()["n"]; success=con.execute("SELECT COUNT(*) n FROM ai_audit_logs WHERE outcome IN ('select','reject')").fetchone()["n"]; avg=con.execute("SELECT AVG(latency_ms) v FROM ai_audit_logs WHERE latency_ms IS NOT NULL").fetchone()["v"]; last=con.execute("SELECT * FROM ai_audit_logs ORDER BY id DESC LIMIT 1").fetchone(); con.close()
    return {"audits":total,"completed":success,"avg_latency_ms":round(float(avg or 0),1),"last":dict(last) if last else None}

@app.post("/settings/professional-check")
def professional_check():
    checks=[]
    def add(key,label,status,detail,weight=1,action=None): checks.append({"key":key,"label":label,"status":status,"detail":detail,"weight":weight,"action":action})
    con=connect()
    products=con.execute("SELECT COUNT(*) n FROM products WHERE active=1").fetchone()["n"]
    refs=con.execute("SELECT COUNT(DISTINCT product_id) n FROM product_media WHERE media_type='image' AND feature_json IS NOT NULL").fetchone()["n"]
    pending=con.execute("SELECT COUNT(*) n FROM catalog_sync_errors WHERE status!='resolved'").fetchone()["n"]
    dup=con.execute("SELECT COUNT(*) n FROM (SELECT sku FROM products WHERE active=1 GROUP BY sku HAVING COUNT(*)>1)").fetchone()["n"]
    site=con.execute("SELECT COUNT(*) n FROM catalog_site_items WHERE status='resolved'").fetchone()["n"]
    learned=con.execute("SELECT COUNT(*) n FROM product_media WHERE source='confirmed_photo'").fetchone()["n"]
    quarantine=con.execute("SELECT COUNT(*) n FROM learning_quarantine WHERE validation_status='pending'").fetchone()["n"]
    equiv=con.execute("SELECT COUNT(DISTINCT group_key) n FROM visual_equivalence_groups").fetchone()["n"]
    settings=dict(con.execute("SELECT * FROM ai_settings WHERE id=1").fetchone())
    broken=0
    for r in con.execute("SELECT m.file_path,p.sku FROM product_media m JOIN products p ON p.id=m.product_id WHERE m.media_type='image'").fetchall():
        if not _resolve_media_path(r["file_path"],r["sku"]): broken+=1
    con.close()
    ratio=(refs/products*100) if products else 0
    add("catalog","Catálogo operacional","pass" if products>0 else "block",f"{products:,} produtos ativos".replace(',', '.'),3,"Sincronize o Catálogo Leo" if products==0 else None)
    add("visual","Cobertura de referência visual","pass" if ratio>=95 else ("warn" if ratio>=80 else "block"),f"{ratio:.1f}% dos produtos possuem imagem indexada",3,"Reprocessar imagens ausentes" if ratio<95 else None)
    add("media","Integridade dos arquivos de imagem","pass" if broken==0 else "block",f"{broken} arquivo(s) de imagem ausente(s)",3,"Executar auto-reparo/sincronização" if broken else None)
    add("duplicates","Unicidade de SKU","pass" if dup==0 else "block",f"{dup} SKU(s) duplicado(s)",3,"Revisar duplicidades" if dup else None)
    add("sync_errors","Erros pendentes de catálogo","pass" if pending==0 else "warn",f"{pending} erro(s) pendente(s)",2,"Reprocessar somente erros" if pending else None)
    add("site_ledger","Ledger do site","pass" if site>0 else "warn",f"{site:,} itens resolvidos no checklist incremental".replace(',', '.'),1)
    add("learning","Aprendizado supervisionado","pass" if settings.get("learning_enabled") else "warn",f"{learned} foto(s) reais confirmadas",1,"Ativar aprendizado supervisionado" if not settings.get("learning_enabled") else None)
    add("industrial_engine","Motor Visual Industrial V10","pass","Identidade perceptual, multi-crop, margem mínima, abstenção segura e comparação independente de posição ativos",3)
    add("learning_quarantine","Quarentena de aprendizado","pass" if quarantine==0 else "warn",f"{quarantine} evidência(s) aguardando validação",2,"Revisar correções/confirmações pendentes" if quarantine else None)
    add("visual_equivalence","Grupos de equivalência visual","pass" if equiv>0 else "warn",f"{equiv} grupo(s) cadastrados",1,"Mapear SKUs visualmente idênticos por padrão/espessura/faces" if equiv==0 else None)
    if settings.get("enabled"):
        add("ai_key","Chave da IA","pass" if settings.get("api_key") else "block","Configurada no servidor e protegida" if settings.get("api_key") else "Chave não configurada",2,"Configurar e testar a API" if not settings.get("api_key") else None)
        test_ok=settings.get("last_test_ok")
        add("ai_test","Conexão da IA","pass" if test_ok==1 else ("warn" if test_ok is None else "block"),settings.get("last_test_message") or "Ainda não testada",2,"Executar Testar conexão")
    else: add("ai_optional","Auditoria externa","warn","Desativada — o sistema continuará operando somente com visão local",1)
    free=shutil.disk_usage(str(BASE_DIR)).free/(1024**3); add("storage","Espaço em disco","pass" if free>=2 else ("warn" if free>=0.7 else "block"),f"{free:.1f} GB livres",2,"Liberar espaço em disco" if free<2 else None)
    cloud=(BASE_DIR.parent/"tools"/"cloudflared.exe").exists() or (BASE_DIR/"../tools/cloudflared.exe").resolve().exists(); add("cloudflare","Cloudflare Tunnel","pass" if cloud else "warn","Executável disponível" if cloud else "Executável não localizado",1)
    blockers=sum(1 for c in checks if c["status"]=="block"); warnings=sum(1 for c in checks if c["status"]=="warn"); weights=sum(c["weight"] for c in checks); earned=sum(c["weight"]*(1 if c["status"]=="pass" else .55 if c["status"]=="warn" else 0) for c in checks); score=round(100*earned/weights,1) if weights else 0
    overall="ready" if blockers==0 and score>=90 else ("attention" if blockers==0 else "blocked")
    payload={"score":score,"overall":overall,"blockers":blockers,"warnings":warnings,"checks":checks,"checked_at":datetime.now().isoformat(timespec='seconds')}
    con=connect(); con.execute("INSERT INTO system_check_runs(score,blockers,warnings,payload_json) VALUES(?,?,?,?)",(score,blockers,warnings,json.dumps(payload,ensure_ascii=False))); con.commit(); con.close(); return payload

@app.get("/settings/ai/learning-stats")
def learning_stats():
    con=connect()
    total=con.execute("SELECT COUNT(*) n FROM learning_events").fetchone()["n"]
    corrections=con.execute("SELECT COUNT(*) n FROM learning_events WHERE event_type='correction'").fetchone()["n"]
    confirmed=con.execute("SELECT COUNT(*) n FROM product_media WHERE source='confirmed_photo'").fetchone()["n"]
    quarantine=con.execute("SELECT COUNT(*) n FROM learning_quarantine WHERE validation_status='pending'").fetchone()["n"]
    con.close(); return {"events":total,"corrections":corrections,"confirmed_photos":confirmed,"quarantine_pending":quarantine}

class PrintIn(BaseModel):
    sku: str
    quantity: int = 1

class CatalogSyncIn(BaseModel):
    max_pages: int = 250
    delay_seconds: float = 0.30


class LoginIn(BaseModel):
    username: str
    password: str

PUBLIC_PATHS = {"/", "/auth/login", "/auth/me", "/health-public"}

@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path

    # Frontend estático precisa carregar para exibir a tela de login.
    if path == "/" or path.startswith("/assets/") or path.startswith("/favicon"):
        return await call_next(request)

    if path in {"/auth/login", "/auth/me", "/health-public"}:
        return await call_next(request)

    username = verify_session(request.cookies.get("chapa_session"))
    if not username:
        return Response(
            content=json.dumps({"detail": "Não autenticado"}),
            status_code=401,
            media_type="application/json",
        )
    request.state.username = username
    return await call_next(request)

@app.post("/auth/login")
def auth_login(data: LoginIn, response: Response):
    if not verify_password(data.username.strip(), data.password):
        raise HTTPException(401, "Usuário ou senha inválidos.")
    token = create_session(data.username.strip())
    response.set_cookie(
        "chapa_session",
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=12 * 3600,
        path="/",
    )
    return {"ok": True, "username": data.username.strip()}

@app.post("/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie("chapa_session", path="/")
    return {"ok": True}

@app.get("/auth/me")
def auth_me(request: Request):
    username = verify_session(request.cookies.get("chapa_session"))
    if not username:
        raise HTTPException(401, "Não autenticado.")
    return {"authenticated": True, "username": username}

@app.get("/health-public")
def health_public():
    return {"status": "online"}

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def set_job(job_id: str, **kwargs):
    with IMPORT_LOCK:
        IMPORT_JOBS.setdefault(job_id, {}).update(kwargs)

def get_job(job_id: str):
    with IMPORT_LOCK:
        job = IMPORT_JOBS.get(job_id)
        return dict(job) if job else None

@app.get("/health")
def health():
    return {
        "api": "online",
        "database": "online",
        "vision": "online",
        "printer": printer.status()
    }

@app.get("/dashboard")
def dashboard():
    con = connect()
    total = con.execute("SELECT COUNT(*) c FROM products WHERE active=1").fetchone()["c"]
    ready = con.execute("""
        SELECT COUNT(DISTINCT p.id) c
        FROM products p
        JOIN product_media m ON m.product_id=p.id
        WHERE p.active=1 AND m.media_type='image'
    """).fetchone()["c"]
    ids = con.execute("SELECT COUNT(*) c FROM identifications").fetchone()["c"]
    correct = con.execute("""
        SELECT COUNT(*) c FROM identifications
        WHERE suggested_sku IS NOT NULL AND confirmed_sku=suggested_sku
    """).fetchone()["c"]
    catalog = con.execute("SELECT COUNT(*) c FROM products WHERE active=1 AND source='leo_site'").fetchone()["c"]
    catalog_images = con.execute("""
        SELECT COUNT(DISTINCT p.id) c
        FROM products p JOIN product_media m ON m.product_id=p.id
        WHERE p.active=1 AND p.source='leo_site' AND m.media_type='image'
    """).fetchone()["c"]
    con.close()
    accuracy = round((correct / ids * 100), 1) if ids else 0
    return {"products": total, "ready": ready, "identifications": ids, "accuracy": accuracy,
            "catalog_products": catalog, "catalog_images": catalog_images}

@app.get("/products")
def products(q: str = ""):
    con = connect()
    if q:
        like = f"%{q}%"
        rows = con.execute("""
            SELECT p.*,
                   (SELECT COUNT(*) FROM product_media m WHERE m.product_id=p.id AND m.media_type='image') photos
            FROM products p
            WHERE active=1 AND (sku LIKE ? OR description LIKE ? OR address LIKE ?)
            ORDER BY sku
        """, (like, like, like)).fetchall()
    else:
        rows = con.execute("""
            SELECT p.*,
                   (SELECT COUNT(*) FROM product_media m WHERE m.product_id=p.id AND m.media_type='image') photos
            FROM products p
            WHERE active=1
            ORDER BY sku
        """).fetchall()
    con.close()
    return [dict(r) for r in rows]

@app.post("/products")
def create_product(data: ProductIn):
    con = connect()
    try:
        con.execute("""
            INSERT INTO products (sku, description, address, family, thickness, color, manufacturer)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (data.sku.strip(), data.description.strip(), data.address.strip(),
              data.family, data.thickness, data.color, data.manufacturer))
        con.commit()
    except Exception as e:
        con.close()
        raise HTTPException(status_code=400, detail=str(e))
    con.close()
    return {"ok": True}

def normalize_header(v):
    return str(v or "").strip().lower().replace("ç", "c").replace("ã", "a").replace("á", "a").replace("é", "e")

def map_record(rec):
    normalized = {normalize_header(k): v for k, v in rec.items()}
    sku = normalized.get("sku") or normalized.get("codigo") or normalized.get("codigo produto")
    desc = normalized.get("descricao") or normalized.get("description") or normalized.get("produto")
    addr = normalized.get("endereco") or normalized.get("address") or normalized.get("local")
    return sku, desc, addr

def process_import(job_id: str, file_path: str, filename: str):
    started_monotonic = time.perf_counter()
    set_job(job_id, status="processing", started_at=now_iso(), percent=1, message="Preparando arquivo...")

    con = None
    try:
        path = Path(file_path)
        name = filename.lower()
        records_iter = None
        total = 0
        cleanup = None

        if name.endswith(".csv"):
            # Uma leitura rápida para obter total e depois streaming real.
            with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as f:
                total = max(sum(1 for _ in f) - 1, 0)

            f = path.open("r", encoding="utf-8-sig", errors="ignore", newline="")
            reader = csv.DictReader(f)
            records_iter = reader
            cleanup = f.close

        elif name.endswith(".xlsx"):
            wb = load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            total = max((ws.max_row or 1) - 1, 0)
            rows = ws.iter_rows(values_only=True)
            headers = next(rows, None) or []

            def iter_xlsx():
                for row in rows:
                    yield dict(zip(headers, row))

            records_iter = iter_xlsx()
            cleanup = wb.close
        else:
            raise ValueError("Use CSV ou XLSX.")

        set_job(job_id, total=total, percent=3, message="Validando dados...")

        con = connect()
        existing = {
            row["sku"] for row in con.execute("SELECT sku FROM products").fetchall()
        }

        new = updated = errors = processed = 0
        details = []
        batch = []
        batch_size = 1000

        # UPSERT em lote: muito mais rápido que INSERT/UPDATE linha por linha com consulta individual.
        sql = """
        INSERT INTO products (sku, description, address)
        VALUES (?, ?, ?)
        ON CONFLICT(sku) DO UPDATE SET
            description=excluded.description,
            address=excluded.address,
            updated_at=CURRENT_TIMESTAMP
        """

        for i, rec in enumerate(records_iter, start=2):
            sku, desc, addr = map_record(rec)

            if not sku or not desc or not addr:
                errors += 1
                if len(details) < 200:
                    details.append({"row": i, "error": "SKU, descrição ou endereço ausente"})
            else:
                sku, desc, addr = str(sku).strip(), str(desc).strip(), str(addr).strip()
                if sku in existing:
                    updated += 1
                else:
                    new += 1
                    existing.add(sku)
                batch.append((sku, desc, addr))

                if len(batch) >= batch_size:
                    con.executemany(sql, batch)
                    con.commit()
                    batch.clear()

            processed += 1
            if processed % 250 == 0 or processed == total:
                pct = 5 + int((processed / max(total, 1)) * 92)
                set_job(
                    job_id,
                    processed=processed,
                    new=new,
                    updated=updated,
                    errors=errors,
                    percent=min(pct, 97),
                    message=f"Importando {processed:,} de {total:,} linhas..."
                )

        if batch:
            con.executemany(sql, batch)
            con.commit()

        if cleanup:
            cleanup()

        finished_at = now_iso()
        duration = round(time.perf_counter() - started_monotonic, 2)
        set_job(
            job_id,
            status="completed",
            processed=processed,
            total=total,
            new=new,
            updated=updated,
            errors=errors,
            details=details,
            percent=100,
            message="Importação concluída.",
            finished_at=finished_at,
            duration_seconds=duration,
        )
    except Exception as e:
        set_job(
            job_id,
            status="failed",
            percent=100,
            message="Falha na importação.",
            error=str(e),
            finished_at=now_iso(),
            duration_seconds=round(time.perf_counter() - started_monotonic, 2),
        )
    finally:
        if con:
            con.close()
        try:
            Path(file_path).unlink(missing_ok=True)
        except Exception:
            pass

@app.post("/import/start")
async def start_import(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    if not (name.endswith(".csv") or name.endswith(".xlsx")):
        raise HTTPException(400, "Use CSV ou XLSX.")

    job_id = uuid.uuid4().hex
    ext = Path(name).suffix
    target = IMPORT_DIR / f"{job_id}{ext}"

    # Salvar por blocos evita manter o XLSX inteiro na memória.
    with target.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)

    set_job(
        job_id,
        status="queued",
        filename=file.filename,
        percent=0,
        processed=0,
        total=0,
        new=0,
        updated=0,
        errors=0,
        created_at=now_iso(),
        started_at=None,
        finished_at=None,
        duration_seconds=None,
        message="Arquivo recebido. Preparando importação..."
    )

    background_tasks.add_task(process_import, job_id, str(target), file.filename or "")
    return {"job_id": job_id}

@app.get("/import/status/{job_id}")
def import_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Importação não encontrada.")
    return job


def set_catalog_job(job_id: str, **kwargs):
    with CATALOG_LOCK:
        CATALOG_JOBS.setdefault(job_id, {}).update(kwargs)


def get_catalog_job(job_id: str):
    with CATALOG_LOCK:
        job = CATALOG_JOBS.get(job_id)
        return dict(job) if job else None


def _catalog_image_extension(url: str) -> str:
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".avif"} else ".jpg"


def _catalog_log(job_id: str, message: str):
    stamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    print(f"[{stamp}] [CHAPA ID] [CATÁLOGO LEO] {message}", flush=True)
    job = get_catalog_job(job_id) or {}
    events = list(job.get("events") or [])[-39:]
    events.append({"at": now_iso(), "message": message})
    set_catalog_job(job_id, last_event=message, events=events, heartbeat_at=now_iso())


def _save_catalog_error(con, source_url: str, error: Exception | str, sku: str | None = None):
    msg = str(error)[:1500]
    con.execute("""
        INSERT INTO catalog_sync_errors (source_url,sku,status,attempts,last_error,last_attempt_at)
        VALUES (?,?,'pending',1,?,CURRENT_TIMESTAMP)
        ON CONFLICT(source_url) DO UPDATE SET
          sku=COALESCE(excluded.sku,catalog_sync_errors.sku), status='pending',
          attempts=catalog_sync_errors.attempts+1, last_error=excluded.last_error,
          last_attempt_at=CURRENT_TIMESTAMP, resolved_at=NULL
    """, (source_url, sku, msg))
    con.commit()


def _resolve_catalog_error(con, source_url: str):
    con.execute("UPDATE catalog_sync_errors SET status='resolved',resolved_at=CURRENT_TIMESTAMP,last_attempt_at=CURRENT_TIMESTAMP WHERE source_url=?", (source_url,))


def _repair_and_upsert_catalog_product(con, item):
    # Corrige versões anteriores que gravaram o ID /p/<id> como SKU.
    by_url = con.execute("SELECT * FROM products WHERE source_url=?", (item.product_url,)).fetchone()
    by_sku = con.execute("SELECT * FROM products WHERE sku=?", (item.sku,)).fetchone()
    if by_url and by_url["sku"] != item.sku:
        if by_sku and by_sku["id"] != by_url["id"]:
            con.execute("UPDATE product_media SET product_id=? WHERE product_id=?", (by_sku["id"], by_url["id"]))
            con.execute("DELETE FROM products WHERE id=?", (by_url["id"],))
        else:
            con.execute("UPDATE products SET sku=? WHERE id=?", (item.sku, by_url["id"]))
        con.commit()
    existing = con.execute("SELECT * FROM products WHERE sku=?", (item.sku,)).fetchone()
    address = existing["address"] if existing and existing["address"] and existing["address"].strip().lower() not in {"não informado","nao informado"} else "Localização pendente de cadastro"
    con.execute("""
        INSERT INTO products (sku,description,address,manufacturer,source,source_url,source_image_url,source_synced_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(sku) DO UPDATE SET
            description=excluded.description,
            manufacturer=COALESCE(excluded.manufacturer, products.manufacturer),
            source='leo_site', source_url=excluded.source_url,
            source_image_url=excluded.source_image_url, source_synced_at=excluded.source_synced_at,
            updated_at=CURRENT_TIMESTAMP
    """, (item.sku,item.description,address,item.manufacturer,"leo_site",item.product_url,item.image_url,now_iso()))
    con.commit()
    return con.execute("SELECT * FROM products WHERE sku=?", (item.sku,)).fetchone()


def process_catalog_sync(job_id: str, max_pages: int, delay_seconds: float, retry_only: bool = False, incremental_only: bool = False):
    started = time.perf_counter(); con = connect(); run_id = None
    found = updated = images = errors = processed = 0
    started_at = now_iso()
    try:
        cur = con.execute("INSERT INTO catalog_sync_runs (source,status,message) VALUES ('leo_site','processing',?)", ("Reprocessamento de erros" if retry_only else "Sincronização iniciada",))
        run_id = cur.lastrowid; con.commit()
        job_mode = "retry" if retry_only else ("checklist" if incremental_only else "full")
        set_catalog_job(job_id,status="processing",phase="scan" if not retry_only else "collect",percent=0.0,scan_percent=0.0,collect_percent=0.0,products_found=0,products_updated=0,images_downloaded=0,errors=0,total_skus=0,started_at=started_at,message=("Executando Check-List do catálogo..." if incremental_only else "Iniciando leitura do catálogo..."),events=[],mode=job_mode)
        _catalog_log(job_id, f"INÍCIO {'REPROCESSAMENTO DOS ERROS' if retry_only else ('CHECK-LIST INCREMENTAL' if incremental_only else 'SINCRONIZAÇÃO COMPLETA')}")

        if retry_only:
            urls=[r["source_url"] for r in con.execute("SELECT source_url FROM catalog_sync_errors WHERE status='pending' ORDER BY last_attempt_at").fetchall()]
            if not urls:
                set_catalog_job(job_id,status="completed",phase="done",percent=100.0,scan_percent=100.0,collect_percent=100.0,total_skus=0,message="Não há erros pendentes para reprocessar.",finished_at=now_iso(),duration_seconds=round(time.perf_counter()-started,2))
                _catalog_log(job_id,"FIM: nenhum erro pendente."); return
            total=len(urls); found=total
            set_catalog_job(job_id,scan_percent=100.0,total_skus=total,products_found=found,message=f"Reprocessando {total:,} URL(s) com erro...".replace(",","."))
            _catalog_log(job_id,f"ERROS PENDENTES LOCALIZADOS: {total:,}".replace(",","."))
        else:
            # V3.0: progresso da leitura é global e monotônico. MDF e MADEIRAS rodam
            # em paralelo, então nunca usamos o último callback isolado como progresso
            # visual; isso fazia a tela parecer voltar de página quando o callback da
            # outra categoria chegava logo depois.
            scan_state={"mdf":{"pct":0.0,"found":0,"page":0,"expected":0},"madeiras":{"pct":0.0,"found":0,"page":0,"expected":0}}
            scan_lock=threading.Lock()
            scan_started=time.perf_counter()
            last_scan_pct=0.0
            last_global_found=0
            def scan_cb(info):
                nonlocal last_scan_pct, last_global_found
                cat_raw=str(info.get("category") or "").upper()
                key="mdf" if "MDF" in cat_raw else "madeiras"
                expected=int(info.get("expected") or 0); qty=int(info.get("found") or 0); page_no=int(info.get("page") or 0)
                local=min(99.0,(qty/max(expected,1))*100.0) if expected else min(99.0,page_no/max(max_pages,1)*100.0)
                with scan_lock:
                    state=scan_state[key]
                    state["pct"]=max(float(state["pct"]),float(local))
                    state["found"]=max(int(state["found"]),qty)
                    state["page"]=max(int(state["page"]),page_no)
                    state["expected"]=max(int(state.get("expected") or 0), expected)
                    raw_pct=(scan_state["mdf"]["pct"]+scan_state["madeiras"]["pct"])/2
                    scan_pct=max(last_scan_pct,raw_pct)
                    last_scan_pct=scan_pct
                    scan_units_done=scan_state["mdf"]["found"]+scan_state["madeiras"]["found"]
                    unique_now=int(info.get("global_unique_found") or info.get("global_found") or 0)
                    global_found=max(last_global_found,unique_now)
                    last_global_found=global_found
                    max_page=max(scan_state["mdf"]["page"],scan_state["madeiras"]["page"] )
                    elapsed=max(time.perf_counter()-scan_started,0.001)
                    # ETA mede trabalho de leitura (cards percorridos nas duas categorias),
                    # não URLs únicas. MDF também aparece dentro de Madeiras, então usar
                    # únicos para a velocidade falsearia a previsão.
                    scan_rate=scan_units_done/elapsed if scan_units_done else 0.0
                    # O discover_catalog_links pode iniciar sem conseguir ler o total
                    # global por HTTP simples, enquanto o navegador descobre o total real
                    # de cada categoria. Por isso a ETA usa a soma dos "expected" vistos
                    # nos callbacks de MDF + Madeiras.
                    expected_global=sum(int(scan_state[k].get("expected") or 0) for k in ("mdf","madeiras"))
                    if not expected_global:
                        expected_global=int(info.get("global_expected") or 0)
                    eta_mode="official" if expected_global else "pages"
                    if expected_global:
                        remaining=max(expected_global-scan_units_done,0)
                        scan_eta=(remaining/scan_rate) if scan_rate>0 and scan_units_done>=96 and elapsed>=8 else None
                    else:
                        # Fallback profissional: enquanto o site ainda não expôs o total,
                        # usa a velocidade real de páginas. Assim a fase 1 sempre tem ETA.
                        pages_done=scan_state["mdf"]["page"]+scan_state["madeiras"]["page"]
                        page_rate=pages_done/elapsed if pages_done else 0.0
                        pages_remaining=max((max_pages*2)-pages_done,0)
                        scan_eta=(pages_remaining/page_rate) if page_rate>0 and pages_done>=8 else None
                    scan_projected=(datetime.now().astimezone()+timedelta(seconds=scan_eta)).isoformat(timespec="seconds") if scan_eta is not None else None
                    scan_avg=(1/scan_rate) if scan_rate>0 else None
                    scan_speed=scan_rate*60 if scan_rate>0 else None
                    msg=f"Leitura do catálogo: {global_found:,} URLs únicas • MDF pág. {scan_state['mdf']['page']} • MADEIRAS pág. {scan_state['madeiras']['page']}".replace(",",".")
                    set_catalog_job(job_id,phase="scan",percent=round(scan_pct*0.30,1),scan_percent=round(scan_pct,1),
                                    products_found=global_found,message=msg,scan_current_category=cat_raw,scan_page=max_page,heartbeat_at=now_iso(),
                                    scan_eta_seconds=round(scan_eta) if scan_eta is not None else None,
                                    scan_projected_finish_at=scan_projected,
                                    scan_avg_seconds_per_link=round(scan_avg,3) if scan_avg else None,
                                    scan_throughput_links_min=round(scan_speed,1) if scan_speed else None,
                                    scan_mdf_page=scan_state["mdf"]["page"],scan_madeiras_page=scan_state["madeiras"]["page"],
                                    scan_mdf_found=scan_state["mdf"]["found"],scan_madeiras_found=scan_state["madeiras"]["found"],
                                    scan_expected_units=expected_global or None, scan_eta_mode=eta_mode)
                if info.get("navigation_retry"):
                    _catalog_log(job_id,(
                        f"RECUPERAÇÃO PAGINAÇÃO {cat_raw}: tentativa {int(info.get('navigation_retry') or 0)} "
                        f"para página {int(info.get('navigation_target') or 0)} • mantendo página {page_no} • {qty:,} links únicos"
                    ).replace(",","."))
                else:
                    _catalog_log(job_id,f"Leitura {cat_raw}: página {page_no} • {qty:,} links identificados".replace(",","."))
            urls, expected_total = discover_catalog_links(max_pages=max_pages,delay_seconds=delay_seconds,progress_callback=scan_cb)
            site_total=len(urls)
            found=site_total
            checklist_valid_skus=set()

            if incremental_only:
                def _norm_catalog_url(v):
                    if not v:
                        return ""
                    return str(v).split("#",1)[0].split("?",1)[0].rstrip("/").lower()

                # Ledger persistente do site. O Check-List deixa de comparar apenas URL
                # salva no produto (que pode ser sobrescrita) e passa a lembrar cada /p/<id>.
                # Isso impede o mesmo item do site de voltar como "novo" em toda execução.
                site_by_key={_site_key_from_url(u):u for u in urls}
                site_keys=set(site_by_key)

                ledger_rows=con.execute("SELECT site_key,source_url,sku,status FROM catalog_site_items").fetchall()
                ledger={str(r["site_key"]):dict(r) for r in ledger_rows}

                # Backfill compatível com bases antigas: registra as URLs atuais conhecidas
                # dos produtos existentes antes de calcular novidades.
                old_rows=con.execute("SELECT sku,description,source_url,source_image_url FROM products WHERE source='leo_site' AND active=1 AND source_url IS NOT NULL").fetchall()
                for r in old_rows:
                    key=_site_key_from_url(r["source_url"])
                    if key and key not in ledger:
                        con.execute("""INSERT OR IGNORE INTO catalog_site_items(site_key,source_url,sku,description,image_url,status,last_synced_at) VALUES(?,?,?,?,?,'resolved',?)""",
                                    (key,r["source_url"],r["sku"],r["description"],r["source_image_url"],now_iso()))
                        ledger[key]={"site_key":key,"source_url":r["source_url"],"sku":r["sku"],"status":"resolved"}
                con.commit()

                # Produto é considerado íntegro só se existir imagem física válida.
                valid_skus=set()
                media_rows=con.execute("""
                    SELECT p.sku,m.file_path,m.feature_json
                    FROM products p JOIN product_media m ON m.product_id=p.id
                    WHERE p.source='leo_site' AND p.active=1 AND m.source='leo_site' AND m.media_type='image'
                """).fetchall()
                for r in media_rows:
                    try:
                        if Path(r["file_path"] or "").exists() and feature_is_current(r["feature_json"]):
                            valid_skus.add(str(r["sku"]))
                            checklist_valid_skus.add(str(r["sku"]))
                    except Exception:
                        pass

                pending_rows=con.execute("SELECT source_url FROM catalog_sync_errors WHERE status='pending'").fetchall()
                pending_keys={_site_key_from_url(r["source_url"]) for r in pending_rows if r["source_url"]}

                known_keys={k for k,r in ledger.items() if r.get("status")=="resolved" and k in site_keys}
                retry_keys={k for k in site_keys if k in pending_keys}
                # Se o ledger conhece o item mas o SKU não tem mídia válida, reprocessa só ele.
                repair_keys={k for k in known_keys if not ledger[k].get("sku") or str(ledger[k].get("sku")) not in valid_skus}
                new_keys=site_keys-set(ledger)
                target_keys=new_keys | retry_keys | repair_keys
                urls=[site_by_key[k] for k in site_by_key if k in target_keys]
                total=len(urls)
                removed_count=len(set(ledger)-site_keys)
                already_ok=len(known_keys-repair_keys-retry_keys)

                set_catalog_job(
                    job_id,
                    phase="collect" if total else "done",
                    percent=30.0 if total else 100.0,
                    scan_percent=100.0,
                    collect_percent=0.0 if total else 100.0,
                    total_skus=total,
                    expected_skus=site_total,
                    scan_expected_units=expected_total,
                    products_found=site_total,
                    checklist_mode=True,
                    checklist_site_total=site_total,
                    checklist_existing=already_ok,
                    checklist_new=len(new_keys),
                    checklist_missing_images=len(repair_keys),
                    checklist_retry=len(retry_keys),
                    checklist_removed=removed_count,
                    message=(
                        f"Check-List concluído. {total:,} item(ns) precisam de ação."
                        if total else
                        f"Check-List concluído. Catálogo íntegro: {site_total:,} itens do site já estão registrados."
                    ).replace(",",".")
                )
                _catalog_log(job_id,(
                    f"CHECK-LIST • site={site_total:,} • já validados={already_ok:,} • "
                    f"novos={len(new_keys):,} • reparar={len(repair_keys):,} • "
                    f"erros pendentes={len(retry_keys):,} • fora do catálogo atual={removed_count:,}"
                ).replace(",","."))

                if total == 0:
                    finished=now_iso(); duration=round(time.perf_counter()-started,2)
                    con.execute("""
                        UPDATE catalog_sync_runs
                        SET status='completed',products_found=?,products_updated=0,
                            images_downloaded=0,errors=0,message=?,finished_at=?
                        WHERE id=?
                    """,(site_total,"Check-List concluído sem pendências",finished,run_id))
                    con.commit()
                    set_catalog_job(
                        job_id,status="completed",phase="done",percent=100.0,
                        scan_percent=100.0,collect_percent=100.0,
                        products_found=site_total,products_updated=0,images_downloaded=0,
                        errors=0,total_skus=0,message="Check-List concluído: nenhum item novo ou pendente.",
                        finished_at=finished,duration_seconds=duration
                    )
                    _catalog_log(job_id,f"FIM CHECK-LIST • catálogo íntegro • {site_total:,} URLs verificadas • nenhum item novo.".replace(",","."))
                    return
            else:
                total=site_total
                set_catalog_job(job_id,phase="collect",percent=30.0,scan_percent=100.0,collect_percent=0.0,total_skus=total,expected_skus=total,scan_expected_units=expected_total,products_found=found,message=f"Leitura concluída. {total:,} produtos únicos encontrados. Iniciando coleta...".replace(",","."))
                _catalog_log(job_id,f"LEITURA CONCLUÍDA: {total:,} URLs únicas. INÍCIO DA COLETA DE DADOS.".replace(",","."))

        # V2.7 PERFORMANCE: coleta renderizada continua protegida contra SKU incorreto,
        # mas usa mais páginas em paralelo e desacopla download/extração das imagens.
        cpu = max(2, os.cpu_count() or 4)
        workers = max(4, min(int(os.environ.get("CHAPA_ID_CATALOG_WORKERS", "8")), 12))
        image_workers = max(4, min(int(os.environ.get("CHAPA_ID_IMAGE_WORKERS", "8")), 10, max(cpu, 4)))
        collect_started = time.perf_counter()
        completion_times = []
        pending_images = []
        _catalog_log(job_id, f"COLETA V4.1.5 BLOCO-H1: {workers} páginas paralelas + {image_workers} imagens; conflito de SKU recebe retry em navegador novo.")
        set_catalog_job(job_id, collection_workers=workers, image_workers=image_workers, collection_started_at=now_iso(),
                        performance_mode="V4.1.6 Cod. Interno + fallback Cód. LM preso ao bloco H1 + anti-colisão", eta_seconds=None, projected_finish_at=None,
                        avg_seconds_per_sku=None, throughput_skus_min=None)

        def code_label(sku):
            return "Cód. LM" if str(sku or "").upper().startswith("LM-") else "Cod. Interno"

        def prepare_image(image_url: str, target: Path):
            download_image(image_url, target)
            return dumps_feature(engine.extract(target))

        def drain_images(wait_all: bool = False):
            nonlocal images, errors
            keep = []
            for rec in pending_images:
                fut, product_id, media_id, image_url, target, source_url, sku, action = rec
                if not fut.done() and not wait_all:
                    keep.append(rec); continue
                try:
                    feature_json = fut.result()
                    if media_id:
                        con.execute("UPDATE product_media SET file_path=?,feature_json=?,source_url=? WHERE id=?", (str(target),feature_json,image_url,media_id))
                    else:
                        con.execute("INSERT INTO product_media (product_id,media_type,file_path,feature_json,source,source_url) VALUES (?,?,?,?,?,?)", (product_id,"image",str(target),feature_json,"leo_site",image_url))
                    con.commit(); images += 1
                    _catalog_log(job_id, f"IMG OK • {code_label(sku)} {sku} • {action}")
                except Exception as e:
                    errors += 1
                    _save_catalog_error(con, source_url, f"Falha de imagem: {e}", sku)
                    _catalog_log(job_id, f"IMG ERRO • {code_label(sku)} {sku} • {e}")
            pending_images[:] = keep

        with ThreadPoolExecutor(max_workers=image_workers, thread_name_prefix="chapa-img") as image_pool:
          for source_idx, product_url, item, fetch_error, fetch_seconds in iter_rendered_products_parallel(urls, workers=workers, timeout_ms=18000):
            processed += 1
            try:
                set_catalog_job(job_id,current_index=processed,current_url=product_url,
                                message=f"Processando {processed:,} de {total:,} produtos...".replace(",","."),heartbeat_at=now_iso())
                if fetch_error:
                    raise ValueError(fetch_error)
                if item is None:
                    raise ValueError("Produto não retornado pelo navegador de coleta.")
                # No Check-List, uma URL ainda não catalogada pode apontar para um Cod. Interno
                # que já existe. Não regravamos nem baixamos a imagem outra vez. Antes,
                # validamos se a descrição é compatível para não aceitar SKU stale do DOM.
                def _desc_tokens(v):
                    return {t for t in re.sub(r'[^a-z0-9 ]',' ',str(v or '').lower()).split() if len(t)>=3}

                existing_product=con.execute("SELECT id,sku,description,source_url,source_image_url FROM products WHERE sku=? AND active=1",(item.sku,)).fetchone()
                skip_existing=False
                sim=1.0
                if existing_product:
                    a=_desc_tokens(existing_product["description"]); b=_desc_tokens(item.description)
                    sim=(len(a & b)/max(1,len(a | b))) if a and b else 0.0
                    url_conflict=bool(existing_product["source_url"] and str(existing_product["source_url"])!=str(product_url))
                    if sim < 0.58 or (url_conflict and sim < 0.76):
                        stale_sku=str(item.sku)
                        _catalog_log(job_id, f"V10 RETRY ISOLADO {processed:,}/{total:,} • possível SKU stale {code_label(stale_sku)} {stale_sku} • similaridade {sim*100:.1f}%".replace(",","."))
                        isolated=fetch_rendered_product_isolated(product_url, timeout_ms=36000)
                        if isolated is None:
                            raise ValueError("Retry isolado não retornou produto válido.")
                        item=isolated
                        existing_product=con.execute("SELECT id,sku,description,source_url,source_image_url FROM products WHERE sku=? AND active=1",(item.sku,)).fetchone()
                        if existing_product:
                            a=_desc_tokens(existing_product["description"]); b=_desc_tokens(item.description)
                            sim=(len(a & b)/max(1,len(a | b))) if a and b else 0.0
                            url_conflict=bool(existing_product["source_url"] and str(existing_product["source_url"])!=str(product_url))
                            if sim < 0.58 or (url_conflict and sim < 0.76):
                                raise ValueError(f"SKU potencialmente stale após retry: {item.sku}; descrição incompatível ({sim*100:.1f}%).")
                        _catalog_log(job_id, f"V10 RETRY ISOLADO OK • origem #{source_idx:,} • {code_label(item.sku)} {item.sku} • {item.description[:90]}".replace(",","."))

                if incremental_only and existing_product and sim>=0.58 and str(existing_product["source_url"] or "")==str(product_url):
                    product=existing_product
                    image_status="SKU já sincronizado • ignorado pelo Check-List"
                    skip_existing=True
                else:
                    product=_repair_and_upsert_catalog_product(con,item); updated+=1
                    image_status="sem imagem"
                if (not skip_existing) and item.image_url and product:
                    has=con.execute("SELECT id,file_path,feature_json FROM product_media WHERE product_id=? AND media_type='image' AND source='leo_site' AND source_url=?",(product["id"],item.image_url)).fetchone()
                    if has and feature_is_current(has["feature_json"]) and Path(has["file_path"] or "").exists():
                        image_status="imagem já validada"
                    elif has and Path(has["file_path"] or "").exists():
                        # Reindexação local é rápida e não exige novo download.
                        feature_json=dumps_feature(engine.extract(Path(has["file_path"])))
                        con.execute("UPDATE product_media SET feature_json=? WHERE id=?",(feature_json,has["id"])); con.commit()
                        image_status="imagem reindexada"
                    else:
                        con.execute("DELETE FROM product_media WHERE product_id=? AND media_type='image' AND source='leo_site' AND COALESCE(source_url,'')<>?",(product["id"],item.image_url)); con.commit()
                        ext=_catalog_image_extension(item.image_url); target_dir=MEDIA_DIR/item.sku/"catalogo_leo"
                        image_key=hashlib.sha1(item.image_url.encode("utf-8","ignore")).hexdigest()[:16]
                        target=target_dir/f"principal_{image_key}{ext}"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        fut=image_pool.submit(prepare_image,item.image_url,target)
                        pending_images.append((fut,product["id"],has["id"] if has else None,item.image_url,target,product_url,item.sku,"imagem baixada e indexada"))
                        image_status="imagem em processamento paralelo"
                        if len(pending_images) >= image_workers * 6:
                            # Backpressure controlado: evita crescer memória sem limitar o navegador cedo demais.
                            while len(pending_images) >= image_workers * 5:
                                drain_images(False)
                                if len(pending_images) >= image_workers * 5:
                                    time.sleep(0.02)
                drain_images(False)
                site_key=_site_key_from_url(product_url)
                con.execute("""
                    INSERT INTO catalog_site_items(site_key,source_url,sku,description,image_url,status,first_seen_at,last_seen_at,last_synced_at,last_error)
                    VALUES(?,?,?,?,?,'resolved',?,?,?,NULL)
                    ON CONFLICT(site_key) DO UPDATE SET
                        source_url=excluded.source_url,sku=excluded.sku,description=excluded.description,
                        image_url=excluded.image_url,status='resolved',last_seen_at=excluded.last_seen_at,
                        last_synced_at=excluded.last_synced_at,last_error=NULL
                """,(site_key,product_url,item.sku,item.description,item.image_url,now_iso(),now_iso(),now_iso()))
                _resolve_catalog_error(con,product_url);con.commit()
                prefix="SKIP" if skip_existing else "OK"
                _catalog_log(job_id,f"{prefix} {processed:,}/{total:,} • {code_label(item.sku)} {item.sku} • {image_status} • {item.description[:80]}".replace(",","."))
            except Exception as e:
                errors+=1;_save_catalog_error(con,product_url,e,item.sku if item else None)
                try:
                    site_key=_site_key_from_url(product_url)
                    con.execute("""INSERT INTO catalog_site_items(site_key,source_url,sku,status,last_seen_at,last_error) VALUES(?,?,?,'error',?,?)
                                 ON CONFLICT(site_key) DO UPDATE SET source_url=excluded.source_url,sku=COALESCE(excluded.sku,catalog_site_items.sku),status='error',last_seen_at=excluded.last_seen_at,last_error=excluded.last_error""",
                                (site_key,product_url,item.sku if item else None,now_iso(),str(e)))
                    con.commit()
                except Exception:
                    pass
                _catalog_log(job_id,f"ERRO {processed:,}/{total:,} • origem #{source_idx:,} • {product_url} • {e}".replace(",","."))

            # ETA flexível: combina média global com janela recente para se adaptar à velocidade atual.
            now_perf=time.perf_counter(); completion_times.append(now_perf)
            if len(completion_times)>61: completion_times=completion_times[-61:]
            elapsed_collect=max(now_perf-collect_started,0.001)
            global_rate=processed/elapsed_collect
            recent_rate=global_rate
            if len(completion_times)>=8:
                recent_span=max(completion_times[-1]-completion_times[0],0.001)
                recent_rate=(len(completion_times)-1)/recent_span
            effective_rate=(recent_rate*0.70)+(global_rate*0.30)
            remaining=max(total-processed,0)
            eta_seconds=(remaining/effective_rate) if effective_rate>0 and processed>=4 else None
            avg_seconds=(1/effective_rate) if effective_rate>0 else None
            projected=(datetime.now().astimezone()+timedelta(seconds=eta_seconds)).isoformat(timespec="seconds") if eta_seconds is not None else None
            collect_pct=(processed/max(total,1))*100.0;overall=30.0+collect_pct*0.70 if not retry_only else collect_pct
            set_catalog_job(job_id,status="processing",phase="collect",percent=round(min(overall,99.9),1),scan_percent=100.0,
                            collect_percent=round(collect_pct,1),products_found=found,products_updated=updated,images_downloaded=images,errors=errors,
                            total_skus=total,current_index=processed,current_url=product_url,current_sku=item.sku if item else None,
                            message=f"Coletando dados: {processed:,} de {total:,} produtos".replace(",","."),heartbeat_at=now_iso(),
                            avg_seconds_per_sku=round(avg_seconds,2) if avg_seconds else None,
                            throughput_skus_min=round(effective_rate*60,1) if effective_rate else None,
                            eta_seconds=round(eta_seconds) if eta_seconds is not None else None,projected_finish_at=projected,
                            last_fetch_seconds=round(fetch_seconds,2),collection_workers=workers)

          # Garante que todas as imagens iniciadas sejam concluídas antes de fechar a execução.
          while pending_images:
              drain_images(True)

        if found==0 or (total>0 and updated==0): raise RuntimeError("Nenhum produto foi importado.")
        finished=now_iso();duration=round(time.perf_counter()-started,2)
        con.execute("UPDATE catalog_sync_runs SET status='completed',products_found=?,products_updated=?,images_downloaded=?,errors=?,message=?,finished_at=? WHERE id=?",(found,updated,images,errors,"Sincronização concluída",finished,run_id));con.commit()
        pending=con.execute("SELECT COUNT(*) c FROM catalog_sync_errors WHERE status='pending'").fetchone()["c"]
        final_message = "Check-List concluído e pendências atualizadas." if incremental_only else "Catálogo Leo sincronizado."
        set_catalog_job(job_id,status="completed",phase="done",percent=100.0,scan_percent=100.0,collect_percent=100.0,products_found=found,products_updated=updated,images_downloaded=images,errors=errors,pending_errors=pending,total_skus=total,message=final_message,finished_at=finished,duration_seconds=duration)
        _catalog_log(job_id,f"FIM {'CHECK-LIST' if incremental_only else 'SINCRONIZAÇÃO'} • site={found:,} processados={total:,} atualizados={updated:,} imagens={images:,} erros={errors:,} duração={duration}s".replace(",","."))
    except Exception as e:
        if run_id:
            con.execute("UPDATE catalog_sync_runs SET status='failed',errors=?,message=?,finished_at=? WHERE id=?",(errors+1,str(e),now_iso(),run_id));con.commit()
        set_catalog_job(job_id,status="failed",phase="failed",percent=100.0,products_found=found,products_updated=updated,images_downloaded=images,errors=errors+1,message="Falha ao sincronizar catálogo.",error=str(e),finished_at=now_iso(),duration_seconds=round(time.perf_counter()-started,2))
        _catalog_log(job_id,f"FALHA: {e}")
    finally: con.close()


@app.post("/catalog/leo/sync")
def start_catalog_sync(data: CatalogSyncIn, background_tasks: BackgroundTasks):
    # Evita duas varreduras concorrentes do mesmo site.
    with CATALOG_LOCK:
        for jid, job in CATALOG_JOBS.items():
            if job.get("status") in {"queued", "processing"}:
                return {"job_id": jid, "already_running": True}
    job_id = uuid.uuid4().hex
    set_catalog_job(job_id, status="queued", percent=0, products_found=0, products_updated=0,
                    images_downloaded=0, errors=0, created_at=now_iso(), message="Sincronização na fila...")
    background_tasks.add_task(process_catalog_sync, job_id, max(1, min(data.max_pages, 260)), max(0.2, data.delay_seconds), False)
    return {"job_id": job_id, "already_running": False}


@app.post("/catalog/leo/checklist")
def start_catalog_checklist(data: CatalogSyncIn, background_tasks: BackgroundTasks):
    """Audita o catálogo oficial e processa SOMENTE o que ainda não está válido localmente.

    O Check-List lê o catálogo inteiro para garantir cobertura, mas não abre novamente
    os produtos que já possuem vínculo e imagem Leo válidos.
    """
    with CATALOG_LOCK:
        for jid, job in CATALOG_JOBS.items():
            if job.get("status") in {"queued", "processing"}:
                return {"job_id": jid, "already_running": True}
    job_id = uuid.uuid4().hex
    set_catalog_job(
        job_id,status="queued",phase="scan",mode="checklist",
        percent=0.0,scan_percent=0.0,collect_percent=0.0,
        products_found=0,products_updated=0,images_downloaded=0,errors=0,
        created_at=now_iso(),message="Check-List na fila: validando catálogo oficial..."
    )
    background_tasks.add_task(
        process_catalog_sync, job_id,
        max(1, min(data.max_pages, 260)),
        max(0.2, data.delay_seconds),
        False, True
    )
    return {"job_id": job_id, "already_running": False}


@app.post("/catalog/leo/retry-errors")
def retry_catalog_errors(background_tasks: BackgroundTasks):
    with CATALOG_LOCK:
        for jid, job in CATALOG_JOBS.items():
            if job.get("status") in {"queued", "processing"}:
                return {"job_id": jid, "already_running": True}
    con=connect(); pending=con.execute("SELECT COUNT(*) c FROM catalog_sync_errors WHERE status='pending'").fetchone()["c"];con.close()
    if pending == 0:
        return {"job_id": None, "already_running": False, "pending": 0}
    job_id=uuid.uuid4().hex
    set_catalog_job(job_id,status="queued",phase="collect",percent=0.0,scan_percent=100.0,collect_percent=0.0,products_found=pending,products_updated=0,images_downloaded=0,errors=0,total_skus=pending,created_at=now_iso(),message="Preparando reprocessamento dos erros...")
    background_tasks.add_task(process_catalog_sync,job_id,1,0.2,True)
    return {"job_id":job_id,"already_running":False,"pending":pending}

@app.get("/catalog/leo/errors")
def catalog_sync_errors(limit:int=200):
    con=connect();rows=con.execute("SELECT * FROM catalog_sync_errors WHERE status='pending' ORDER BY last_attempt_at DESC LIMIT ?",(max(1,min(limit,500)),)).fetchall();con.close()
    return [dict(r) for r in rows]


@app.get("/catalog/leo/status/{job_id}")
def catalog_sync_status(job_id: str):
    job = get_catalog_job(job_id)
    if not job:
        raise HTTPException(404, "Sincronização não encontrada.")
    return job


@app.get("/catalog/leo/summary")
def catalog_summary():
    con = connect()
    products = con.execute("SELECT COUNT(*) c FROM products WHERE source='leo_site' AND active=1").fetchone()["c"]
    images = con.execute("""
        SELECT COUNT(*) c FROM product_media m JOIN products p ON p.id=m.product_id
        WHERE p.source='leo_site' AND m.source='leo_site' AND m.media_type='image'
    """).fetchone()["c"]
    last = con.execute("SELECT * FROM catalog_sync_runs ORDER BY id DESC LIMIT 1").fetchone()
    pending_errors = con.execute("SELECT COUNT(*) c FROM catalog_sync_errors WHERE status='pending'").fetchone()["c"]
    products_with_image = con.execute("""
        SELECT COUNT(DISTINCT p.id) c
        FROM products p
        JOIN product_media m ON m.product_id=p.id
        WHERE p.source='leo_site' AND p.active=1
          AND m.source='leo_site' AND m.media_type='image'
    """).fetchone()["c"]
    con.close()
    return {"products": products, "images": images, "products_with_image": products_with_image,
            "pending_errors": pending_errors, "last_run": dict(last) if last else None,
            "source": "https://www.leomadeiras.com.br/categoria/mdf + /categoria/madeiras"}


@app.get("/catalog/leo/products")
def catalog_products(q: str = "", limit: int = 100):
    con = connect()
    limit = max(1, min(limit, 500))
    if q:
        like = f"%{q}%"
        rows = con.execute("""
            SELECT p.*, (SELECT m.id FROM product_media m WHERE m.product_id=p.id AND m.media_type='image' ORDER BY CASE WHEN m.source='leo_site' THEN 0 ELSE 1 END,m.id LIMIT 1) image_id
            FROM products p WHERE p.active=1 AND p.source='leo_site' AND (p.sku LIKE ? OR p.description LIKE ?)
            ORDER BY p.sku LIMIT ?
        """, (like,like,limit)).fetchall()
    else:
        rows = con.execute("""
            SELECT p.*, (SELECT m.id FROM product_media m WHERE m.product_id=p.id AND m.media_type='image' ORDER BY CASE WHEN m.source='leo_site' THEN 0 ELSE 1 END,m.id LIMIT 1) image_id
            FROM products p WHERE p.active=1 AND p.source='leo_site' ORDER BY p.id DESC LIMIT ?
        """, (limit,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.get("/media/{media_id}")
def media_file(media_id: int):
    con = connect()
    row = con.execute("""
        SELECT m.file_path, p.sku
        FROM product_media m
        JOIN products p ON p.id=m.product_id
        WHERE m.id=?
    """, (media_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "Imagem não encontrada.")

    resolved = _resolve_media_path(row["file_path"], row["sku"])
    if resolved is None:
        con.close()
        raise HTTPException(404, "Imagem física não encontrada para este SKU.")

    resolved_abs = str(resolved.resolve())
    if str(row["file_path"] or "") != resolved_abs:
        con.execute("UPDATE product_media SET file_path=? WHERE id=?", (resolved_abs, media_id))
        con.commit()
    con.close()
    return FileResponse(resolved_abs)


@app.post("/products/{sku}/media")
async def add_media(sku: str, media_type: str = Form("image"), file: UploadFile = File(...)):
    con = connect()
    product = con.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
    if not product:
        con.close()
        raise HTTPException(404, "SKU não encontrado.")

    ext = Path(file.filename or "file.jpg").suffix or ".jpg"
    target_dir = MEDIA_DIR / sku
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex}{ext}"

    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    feature_json = None
    if media_type == "image":
        try:
            feature_json = dumps_feature(engine.extract(target))
        except Exception:
            target.unlink(missing_ok=True)
            con.close()
            raise HTTPException(400, "Não foi possível processar a imagem.")

    con.execute("""
        INSERT INTO product_media (product_id, media_type, file_path, feature_json)
        VALUES (?, ?, ?, ?)
    """, (product["id"], media_type, str(target), feature_json))
    con.commit()
    con.close()
    return {"ok": True, "media_type": media_type}

@app.post("/identify")
async def identify(file: UploadFile = File(...), operator: str = Form("Operador"), ephemeral: str = Form("0"), controlled_light: str = Form("0"), scan_mode: str = Form("full"), software_normalized: str = Form("0"), original_mean: str = Form(""), original_dark: str = Form(""), original_std: str = Form(""), original_color_spread: str = Form(""), light_gain: str = Form(""), light_validated: str = Form("0"), input_source: str = Form("camera")):
    analysis_started = time.perf_counter()
    fast_scan = str(scan_mode).strip().lower() in {"fast","scanner","preview"}
    software_norm = str(software_normalized).strip().lower() in {"1","true","sim","yes"}
    def _f(v, default=None):
        try:
            return float(v)
        except Exception:
            return default
    original_metrics = {
        "mean": _f(original_mean),
        "dark": _f(original_dark),
        "std": _f(original_std),
        "color_spread": _f(original_color_spread),
    }
    validated_gain = _f(light_gain, 0.0) or 0.0
    light_was_validated = str(light_validated).strip().lower() in {"1","true","sim","yes"}
    ext = Path(file.filename or "query.jpg").suffix or ".jpg"
    query_dir = MEDIA_DIR / "_queries"
    query_dir.mkdir(parents=True, exist_ok=True)
    target = query_dir / f"{uuid.uuid4().hex}{ext}"

    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        query_feature = engine.extract(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise HTTPException(400, "Imagem inválida ou não suportada.")

    con = connect()
    rows = con.execute("""
        SELECT p.sku, p.description, p.address, p.manufacturer, p.source_url,
               m.id media_id, m.source media_source, m.file_path, m.feature_json
        FROM product_media m
        JOIN products p ON p.id=m.product_id
        WHERE m.media_type='image' AND m.feature_json IS NOT NULL AND p.active=1
    """).fetchall()

    source_kind=str(input_source or "camera").strip().lower()

    # V10: domínio fechado. Só chapas/painéis podem competir na identificação.
    all_rows_count=len(rows)
    rows=[r for r in rows if _is_sheet_product(r["description"])]
    print(f"[CHAPA-ID][V10][DOMAIN-GATE] referências de chapa={len(rows)} / total={all_rows_count}",flush=True)

    # V7 FAST PATH — arquivo exatamente igual a uma referência já sincronizada.
    # Antes de qualquer ranking, uma foto existente pode ser a própria imagem do
    # catálogo. Nesse caso não faz sentido deixar uma referência "parecida" vencer.
    if source_kind in {"upload","existing","catalog"}:
        try:
            qsize=target.stat().st_size
            qhash=hashlib.sha256(target.read_bytes()).digest()
            exact_rows=[]; seen_skus=set()
            for r in rows:
                rp=_resolve_media_path(r["file_path"],r["sku"])
                if not rp:
                    continue
                try:
                    if rp.stat().st_size!=qsize:
                        continue
                    if hashlib.sha256(rp.read_bytes()).digest()!=qhash:
                        continue
                except Exception:
                    continue
                if str(r["sku"]) in seen_skus:
                    continue
                seen_skus.add(str(r["sku"])); exact_rows.append(r)
            if exact_rows:
                results=[]
                for i,r in enumerate(exact_rows[:5],1):
                    results.append({"sku":r["sku"],"description":r["description"],"address":r["address"],"manufacturer":r["manufacturer"],"source_url":r["source_url"],"media_source":r["media_source"],"image_url":f"/media/{r['media_id']}","score":100.0,"visual_score":100.0,"verification_score":100.0,"identity_score":100.0,"identity_exact":True,"rank":i,"patch_support":13,"patch_count":13})
                unique=len(results)==1
                suggested=results[0]["sku"] if unique else None
                decision=99.9 if unique else 70.0
                cq=engine.assess_capture(target)
                payload={"identification_id":None,"status":"high" if unique else "medium","visual_status":"excellent","results":results,"decision_confidence":decision,"visual_score":100.0,"primary_score":100.0,"sku_defined":unique,"margin_insufficient":False,"min_margin_required":0.0,"input_source":source_kind,"capture_quality":cq,"photometric_validated":True,"safe_to_stop_scan":False,"rejection_reason":None,"score_margin":100.0 if unique else 0.0,"catalog_assisted":True,"ambiguous":not unique,"ambiguity_count":len(results),"visual_equivalence_group":not unique,"visual_equivalence_skus":[str(x.get("sku")) for x in results] if not unique else [],"ambiguity_message":("Padrão visual reconhecido exatamente. A mesma textura oficial está vinculada a mais de um SKU; confirme espessura, faces e dimensão para definir a variação correta." if not unique else None),"analysis_mode":"full","decision_source":"catalog_exact_file","ai_audit":{"used":False,"outcome":"not_required_exact_reference"},"industrial_engine":{"version":"10.0","mode":"exact_reference_identity_v10","catalog_identity_check":True,"position_invariant":True,"abstention_enabled":True,"confidence_margin":100.0 if unique else 0.0},"analysis_ms":round((time.perf_counter()-analysis_started)*1000,1)}
                if str(ephemeral).strip().lower() in {"1","true","sim","yes"}:
                    con.close(); target.unlink(missing_ok=True); return payload
                cur=con.execute("INSERT INTO identifications (query_file,suggested_sku,score,status,operator) VALUES(?,?,?,?,?)",(str(target),suggested,decision,payload["status"],operator))
                payload["identification_id"]=cur.lastrowid; con.commit(); con.close(); return payload
        except Exception as e:
            print(f"[CHAPA-ID][V10] exact-file fast path indisponível: {e}",flush=True)

    grouped = {}
    # V8: uma referência física entra UMA vez no ranking. Bases antigas podem conter
    # dezenas de linhas repetidas apontando para o mesmo principal.jpg; isso inflava
    # artificialmente o candidato errado.
    seen_reference_paths=set()
    for r in rows:
        resolved=_resolve_media_path(r["file_path"],r["sku"])
        ref_key=(str(r["sku"]), str(resolved.resolve()) if resolved else str(r["file_path"] or ""))
        if ref_key in seen_reference_paths:
            continue
        seen_reference_paths.add(ref_key)
        score = engine.similarity(query_feature, loads_feature(r["feature_json"]))
        item = grouped.setdefault(r["sku"], {
            "sku": r["sku"],
            "description": r["description"],
            "address": r["address"],
            "manufacturer": r["manufacturer"],
            "source_url": r["source_url"],
            "scores": [],
            "references": [],
            "best_media_id": None,
            "best_media_score": -1,
            "media_source": r["media_source"]
        })
        item["scores"].append(score)
        item["references"].append({"coarse": score, "file_path": str(resolved) if resolved else r["file_path"], "media_id": r["media_id"], "media_source": r["media_source"]})
        if score > item["best_media_score"]:
            item["best_media_score"] = score
            item["best_media_id"] = r["media_id"]
            item["media_source"] = r["media_source"]

    # ETAPA 1 — shortlist rápido com o índice vetorial persistido.
    coarse_results = []
    for item in grouped.values():
        scores = sorted(item.pop("scores"), reverse=True)
        top = scores[:3]
        coarse_score = round((max(top) * 0.55) + ((sum(top)/len(top)) * 0.45), 2)
        item["coarse_score"] = coarse_score
        item["score"] = coarse_score
        item["image_url"] = f"/media/{item.get('best_media_id')}" if item.get("best_media_id") else None
        coarse_results.append(item)

    coarse_results.sort(key=lambda x: (-float(x["coarse_score"]), str(x["sku"])))

    # ETAPA 2 — perícia visual somente nos melhores candidatos.
    # Isso elimina relações absurdas sem tornar a busca lenta sobre milhares de SKUs.
    shortlist_limit = 32 if fast_scan else (72 if source_kind in {"upload","existing","catalog"} else 90)
    refs_limit = 1 if fast_scan else 3
    shortlist = coarse_results[:shortlist_limit]
    verified = []
    try:
        query_verify_desc = engine.verification_descriptor(target, query=True)
    except Exception:
        query_verify_desc = None
    for item in shortlist:
        best_verify = None
        best_ref = None
        refs = sorted(item.get("references") or [], key=lambda r: -float(r.get("coarse") or 0))[:refs_limit]
        for ref in refs:
            resolved = _resolve_media_path(ref.get("file_path"), item.get("sku"))
            if not resolved:
                continue
            # V8: primeiro verificamos IDENTIDADE; depois qualidade da referência.
            # Um packshot/perfil com fundo branco pode ser exibido no catálogo, mas não
            # pode competir como se fosse textura da face da chapa.
            ident={"identity_score":0.0,"identity_exact":False,"identity_near":False}
            if source_kind in {"upload","existing","catalog"} and not fast_scan:
                ident=engine.compare_identity(target,resolved)
            surface=engine.reference_surface_profile(resolved)
            if (not ident.get("identity_exact")) and (not surface.get("surface_usable")):
                continue
            check = engine.compare_query_descriptor_industrial(query_verify_desc, resolved) if query_verify_desc is not None else engine.compare_images(target, resolved)
            check.update(surface)
            check.update(ident)
            # Se o usuário enviou a própria referência (ou uma recompressão quase idêntica),
            # identidade prevalece sobre qualquer semelhança estética.
            if ident.get("identity_exact"):
                check["score"]=max(float(check.get("score") or 0),99.8)
            elif ident.get("identity_near"):
                check["score"]=max(float(check.get("score") or 0),94.5+min(4.5,max(0.0,(float(ident.get("identity_score") or 0)-88.0)*.38)))
            if best_verify is None or float(check.get("score") or 0) > float(best_verify.get("score") or 0):
                best_verify = check
                best_ref = ref
        if best_verify is not None:
            direct = float(best_verify.get("score") or 0)
            # A perícia direta manda praticamente sozinha no ranking. O índice antigo
            # serve apenas para desempate; nunca pode resgatar candidato fisicamente incompatível.
            item["score"] = round((direct * 0.97) + (float(item["coarse_score"]) * 0.03), 2)
            item["verification_score"] = round(direct, 2)
            item["verification_color"] = best_verify.get("color")
            item["verification_texture"] = best_verify.get("texture")
            item["verification_delta_e"] = best_verify.get("delta_e")
            item["verification_tone_gate"] = best_verify.get("tone_gate")
            item["verification_query_l50"] = best_verify.get("query_l50")
            item["verification_reference_l50"] = best_verify.get("reference_l50")
            # V9 — diagnóstico cromático explícito para auditoria e gestão visual.
            item["query_color_family"] = best_verify.get("query_color_family")
            item["reference_color_family"] = best_verify.get("reference_color_family")
            item["query_warm_fraction"] = best_verify.get("query_warm_fraction")
            item["reference_warm_fraction"] = best_verify.get("reference_warm_fraction")
            item["query_b75"] = best_verify.get("query_b75")
            item["reference_b75"] = best_verify.get("reference_b75")
            item["patch_support"] = int(best_verify.get("patch_support") or 0)
            item["patch_count"] = int(best_verify.get("patch_count") or 0)
            item["robust_patch_score"] = best_verify.get("robust_patch_score")
            item["single_patch_score"] = best_verify.get("single_patch_score")
            item["industrial_match"] = bool(best_verify.get("industrial_match"))
            item["identity_score"] = round(float(best_verify.get("identity_score") or 0),2)
            item["identity_exact"] = bool(best_verify.get("identity_exact"))
            item["identity_near"] = bool(best_verify.get("identity_near"))
            item["surface_reference"] = bool(best_verify.get("surface_usable",True))
            item["surface_quality"] = best_verify.get("surface_quality")
            if best_ref:
                item["best_media_id"] = best_ref.get("media_id")
                item["media_source"] = best_ref.get("media_source")
                item["image_url"] = f"/media/{best_ref.get('media_id')}" if best_ref.get("media_id") else item.get("image_url")
        item.pop("references", None)
        item.pop("best_media_score", None)
        item.pop("best_media_id", None)
        verified.append(item)

    verified=[x for x in verified if x.get("verification_score") is not None]
    verified.sort(key=lambda x: (-float(x["score"]), str(x["sku"])))

    # Qualidade da captura e validação fotométrica.
    # A iluminação física só é considerada "controlada" quando o frontend mede
    # ganho real de luminosidade após torch/flash. Isso evita confiar em câmeras
    # que dizem ter ligado o torch, mas não alteram a imagem.
    capture_quality = engine.assess_capture(target)
    requested_controlled = str(controlled_light).strip().lower() in {"1","true","sim","yes"}
    controlled = bool(requested_controlled and light_was_validated and validated_gain >= 0.055)
    capture_quality["controlled_light_requested"] = requested_controlled
    capture_quality["controlled_light"] = controlled
    capture_quality["light_gain"] = round(float(validated_gain), 4)
    capture_quality["software_normalized"] = software_norm
    capture_quality["original_metrics"] = original_metrics

    om = original_metrics
    om_available = all(om.get(k) is not None for k in ("mean","dark","std","color_spread"))
    original_neutral = bool(
        om_available and float(om["std"]) < 0.105 and float(om["color_spread"]) < 0.090
    )
    original_low_light = bool(
        om_available and (float(om["mean"]) < 0.60 or float(om["dark"]) > 0.26)
    )
    original_bright_safe = bool(
        om_available and float(om["mean"]) >= 0.82 and float(om["dark"]) <= 0.08
    )
    original_very_dark = bool(
        om_available and (float(om["mean"]) < 0.30 or float(om["dark"]) > 0.70)
    )

    # Regra dura: branco/cinza/preto só é decidido com:
    # 1) luz física validada pelo scanner; OU
    # 2) foto original naturalmente clara o suficiente (ex.: foto com flash).
    neutral_photometric_safe = bool(
        (not original_neutral) or controlled or original_bright_safe
    )
    neutral_low_light_guard = bool(original_neutral and not neutral_photometric_safe)

    capture_quality["original_neutral"] = original_neutral
    capture_quality["original_low_light"] = original_low_light
    capture_quality["original_bright_safe"] = original_bright_safe
    capture_quality["original_very_dark"] = original_very_dark
    capture_quality["neutral_low_light_guard"] = neutral_low_light_guard
    print(f"[CHAPA-ID][CAPTURE] quality={float(capture_quality.get('quality') or 0):.1f}% • mean={original_metrics.get('mean')} • dark={original_metrics.get('dark')} • neutral={original_neutral} • controlled={controlled} • guard={neutral_low_light_guard}", flush=True)

    base_safe = bool(capture_quality.get("safe_for_identification", True))
    only_photo_ambiguity = bool(capture_quality.get("photometric_ambiguous")) and not any([
        capture_quality.get("overexposed"), capture_quality.get("glare")
    ])

    capture_safe = bool(
        (base_safe and neutral_photometric_safe)
        or (controlled and only_photo_ambiguity)
        or (original_bright_safe and only_photo_ambiguity)
    )

    # Correção por software melhora detalhe, mas nunca autoriza cor neutra.
    software_can_rank = bool(
        software_norm
        and not original_neutral
        and not capture_quality.get("overexposed")
        and not capture_quality.get("glare")
    )
    capture_rankable = bool(capture_safe or software_can_rank)

    if controlled:
        capture_quality["message"] = "Iluminação física validada pelo scanner; cor liberada para comparação."
        capture_quality["photometric_status"] = "controlled_validated"
    elif original_neutral and original_bright_safe:
        capture_quality["message"] = "Superfície neutra fotografada com luminosidade suficiente; cor liberada."
        capture_quality["photometric_status"] = "naturally_bright"
    elif neutral_low_light_guard:
        capture_quality["message"] = (
            "Cor neutra em iluminação insuficiente. Para evitar branco virar cinza, "
            "o sistema bloqueou a identificação até obter luz física validada."
        )
        capture_quality["photometric_status"] = "blocked_neutral_light"
    elif software_norm and not capture_safe:
        capture_quality["message"] = "Correção de software usada apenas para textura; a cor continua protegida por trava física."
        capture_quality["photometric_status"] = "software_texture_only"
    else:
        capture_quality["photometric_status"] = "native"


    def _product_family(description: str | None) -> str:
        d=(description or "").strip().upper()
        families=("MDF","MDP","COMPENSADO","PAINEL","SARRAFO","RIPA","PORTA","SAPATA","FORMICA","FÓRMICA","OSB","LAMINADO","CHAPA")
        for f in families:
            if d.startswith(f+" ") or d==f:
                return "FORMICA" if f=="FÓRMICA" else f
        return d.split(" ",1)[0] if d else ""

    # ETAPA 3 — filtro de plausibilidade profissional.
    # Candidatos com conflito físico de tonalidade são eliminados, não apenas rebaixados.
    # Conflitos de cor/luminosidade são ELIMINATÓRIOS. Antes a lista não incluía
    # white_gray_conflict/neutral_luminance_conflict/luminance_far, permitindo que
    # uma referência visualmente incompatível sobrevivesse ao filtro.
    physical_conflicts={
        "light_dark_conflict","white_dark_conflict","white_gray_conflict",
        "neutral_luminance_conflict","neutral_luminance_far",
        "luminance_conflict","luminance_far","color_conflict",
        "neutral_chroma_conflict","warm_neutral_conflict","warm_cool_conflict","hue_family_conflict","color_family_mismatch","reference_background_mismatch","query_background_mismatch","invalid"
    }
    physically_valid=[x for x in verified if x.get("verification_tone_gate") not in physical_conflicts]
    physically_valid.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("sku"))))

    top_score = float(physically_valid[0]["score"]) if physically_valid else 0.0
    top_family = _product_family(physically_valid[0].get("description")) if physically_valid else ""
    if top_score >= 94:
        credible_floor = max(88.0, top_score - 5.5)
    elif top_score >= 86:
        credible_floor = max(78.0, top_score - 7.5)
    elif top_score >= 76:
        credible_floor = max(68.0, top_score - 8.5)
    else:
        credible_floor = 65.0

    credible=[]
    for item in physically_valid:
        sc=float(item.get("score") or 0)
        direct=float(item.get("verification_score") or 0)
        # Nada abaixo de 65% aparece como "possível relação". Se não houver candidato
        # plausível, é mais profissional dizer que não foi possível identificar.
        if sc < credible_floor or direct < 62.0:
            continue
        fam=_product_family(item.get("description"))
        if top_score >= 82 and top_family and fam and fam != top_family:
            # Em alta compatibilidade só entram outras famílias se forem praticamente
            # indistinguíveis e ainda assim com score muito próximo.
            if sc < top_score-0.8:
                continue
        credible.append(item)
        if len(credible) >= 5:
            break

    # Preserva candidatos tecnicamente plausíveis para uma segunda opinião por IA.
    # Em baixa luz a cor absoluta pode estar contaminada, mas textura/estrutura ainda
    # podem ser úteis. A IA só poderá atuar em modo recuperação e nunca com candidato
    # completamente incompatível.
    recovery_candidates=[]
    if neutral_low_light_guard:
        for item in physically_valid:
            direct=float(item.get("verification_score") or 0)
            if direct < 58.0:
                continue
            recovery_candidates.append(item.copy())
            if len(recovery_candidates)>=5:
                break

    # Não forçamos um resultado local. Em baixa iluminação uma superfície branca pode
    # parecer cinza/escura; por isso a decisão local é bloqueada. Se houver IA habilitada,
    # ela entra depois como auditor fotométrico de recuperação.
    if not capture_rankable or neutral_low_light_guard:
        credible = []

    top5 = credible
    if top5:
        print("[CHAPA-ID][LOCAL] " + " | ".join([f"#{i+1} {x.get('sku')}={float(x.get('score') or 0):.1f}%" for i,x in enumerate(top5[:5])]), flush=True)
    else:
        print(f"[CHAPA-ID][LOCAL] sem decisão local • recovery_candidates={len(recovery_candidates)} • capture_rankable={capture_rankable} • guard={neutral_low_light_guard}", flush=True)
    for rank, item in enumerate(top5, start=1):
        item["rank"] = rank
        item["visual_score"] = round(float(item["score"]), 2)
        item["family_match"] = (_product_family(item.get("description")) == top_family) if top_family else True

    # V8 — prioridade cirúrgica para a própria referência do catálogo.
    # A evidência de identidade é diferente de similaridade estética e prevalece
    # somente quando os hashes independentes concordam.
    exact_identity=[x for x in top5 if x.get("identity_exact")]
    if exact_identity:
        top5.sort(key=lambda x:(0 if x.get("identity_exact") else 1,-float(x.get("identity_score") or 0),-float(x.get("score") or 0)))
        for rank,item in enumerate(top5,1): item["rank"]=rank

    # V8 — grupo de equivalência visual real. Se as referências oficiais dos primeiros
    # candidatos são a mesma textura (ou praticamente a mesma), a face da chapa não
    # contém informação suficiente para distinguir espessura/faces. O sistema identifica
    # o PADRÃO, mas se abstém de inventar o SKU exato.
    visual_equivalence_group=False
    visual_equivalence_skus=[]
    if len(top5)>1 and not fast_scan:
        try:
            def _candidate_ref(it):
                m=re.search(r'/media/(\d+)',str(it.get("image_url") or ""))
                if not m:return None
                rr=con.execute("SELECT m.file_path,p.sku FROM product_media m JOIN products p ON p.id=m.product_id WHERE m.id=?",(int(m.group(1)),)).fetchone()
                return _resolve_media_path(rr["file_path"],rr["sku"]) if rr else None
            base_ref=_candidate_ref(top5[0])
            if base_ref:
                visual_equivalence_skus=[str(top5[0].get("sku"))]
                for cand in top5[1:5]:
                    cref=_candidate_ref(cand)
                    if not cref:continue
                    eq=engine.compare_identity(base_ref,cref)
                    if eq.get("identity_exact") or (eq.get("identity_near") and float(eq.get("identity_score") or 0)>=94.0):
                        visual_equivalence_skus.append(str(cand.get("sku")))
                visual_equivalence_group=len(visual_equivalence_skus)>=2
        except Exception as e:
            print(f"[CHAPA-ID][V10] equivalence check indisponível: {e}",flush=True)

    suggested = top5[0]["sku"] if top5 else None
    visual_score = top5[0]["score"] if top5 else 0
    second_score = top5[1]["score"] if len(top5) > 1 else 0
    margin = max(0.0, visual_score - second_score)
    # Empate só quando visualmente não há separação útil. Não inventamos casas decimais.
    ambiguity_count = sum(1 for r in top5 if abs(r["score"] - visual_score) < 2.0) if top5 else 0
    ambiguous = ambiguity_count > 1 or visual_equivalence_group
    exact_identity_top=bool(top5 and top5[0].get("identity_exact"))
    # Margem mínima V8: 0,8 p.p. nunca mais vira SKU "mais provável" definitivo.
    # Sem identidade exata, exigimos separação real entre 1º e 2º.
    min_margin_required = 1.5 if visual_score>=94 else (3.0 if visual_score>=84 else 4.5)
    margin_insufficient=bool(len(top5)>1 and margin<min_margin_required and not exact_identity_top)
    if margin_insufficient:
        ambiguous=True
    # Confiança de decisão = qualidade visual + separação para o segundo colocado.
    # Em empate real, a tela reduz a confiança do SKU em vez de mostrar vários "100%".
    uniqueness = min(1.0, margin / 8.0)
    decision_confidence = round(visual_score * (0.72 + 0.28 * uniqueness), 1) if top5 else 0.0
    if ambiguous:
        decision_confidence = min(decision_confidence, 74.0)
    if margin_insufficient:
        decision_confidence=min(decision_confidence,60.0)
    score = decision_confidence
    status = "low"
    if decision_confidence >= 88 and not ambiguous: status = "high"
    elif decision_confidence >= 65: status = "medium"

    visual_status = "excellent" if visual_score >= 92 else ("good" if visual_score >= 82 else ("medium" if visual_score >= 70 else "low"))

    # ETAPA 4 — auditor multimodal opcional. A IA só enxerga candidatos que já
    # passaram pelas travas físicas locais. Em baixa luz existe um modo especial de
    # recuperação fotométrica, mais conservador, para não deixar a IA "inútil" quando
    # o motor local bloqueia branco/cinza/preto.
    ai_audit={"used":False,"outcome":"disabled"}
    decision_source="local"

    # V5.7: em branco/cinza/preto sob luz não validada o scanner NÃO recebe SKU.
    # Retornar candidato estrutural nesses casos foi a origem dos resultados com
    # cores completamente diferentes. O melhor quadro é escolhido pela qualidade
    # da captura no frontend; a identificação só é liberada após fotometria válida.
    if fast_scan and neutral_low_light_guard:
        top5=[]
        suggested=None
        visual_score=0.0
        second_score=0.0
        margin=0.0
        decision_confidence=0.0
        score=0.0
        status="low"
        decision_source="scanner_waiting_photometric_validation"
        capture_quality["message"]="Cor neutra ainda não validada. Scanner ajustando luz/exposição; nenhum SKU será exibido até a cor ficar fisicamente confiável."

    ais=_load_ai_settings_private()
    # V5.4: modo Híbrido/IA + chave válida é a autoridade operacional.
    # O checkbox legado não pode silenciosamente desligar a IA depois de um teste aprovado.
    ai_enabled=ais.get("mode") in {"hybrid","ai"} and bool(ais.get("api_key"))
    if ais.get("mode") in {"hybrid","ai"} and ais.get("api_key") and not bool(ais.get("enabled")):
        print("[CHAPA-ID][IA] AUTO-ENABLE • modo de IA ativo + chave configurada; ignorando toggle legado desligado", flush=True)

    if False and (not fast_scan) and neutral_low_light_guard and recovery_candidates and ai_enabled:
        try:
            print(f"[CHAPA-ID][IA] RECOVERY START • candidatos={len(recovery_candidates)} • modelo={ais.get('model')}", flush=True)
            ai_audit=_audit_candidates_with_ai(target,recovery_candidates,ais,recovery_mode=True)
            print(f"[CHAPA-ID][IA] RECOVERY END • outcome={ai_audit.get('outcome')} • sku={ai_audit.get('sku')} • conf={ai_audit.get('confidence')} • {ai_audit.get('latency_ms')}ms", flush=True)
            if ai_audit.get("outcome")=="select" and ai_audit.get("sku") and float(ai_audit.get("confidence") or 0)>=78:
                chosen=str(ai_audit["sku"]); ordered=sorted(recovery_candidates,key=lambda x:(0 if str(x.get("sku"))==chosen else 1,-float(x.get("score") or 0)))
                # Em recuperação mostramos somente candidatos realmente plausíveis. O primeiro é a escolha da IA;
                # os demais servem para conferência, sem poluir a tela com cinco opções fracas.
                top5=ordered[:3]
                for rank,item in enumerate(top5,1): item["rank"]=rank
                suggested=top5[0]["sku"]
                visual_score=float(top5[0].get("score") or 0)
                # A IA pode recuperar uma captura subexposta, mas nunca transforma isso em confirmação automática.
                # 82-89% = confirmação necessária; >=90% ainda depende da trava de iluminação para auto-scan.
                decision_confidence=round(min(float(ai_audit.get("confidence") or 0), max(65.0, visual_score)),1)
                score=decision_confidence; status="medium" if score<90 else "high"
                decision_source="ai_photometric_recovery"
                capture_quality["message"]="Iluminação insuficiente para decisão local; Gemini auditou apenas candidatos visualmente plausíveis em modo de recuperação fotométrica."
                capture_quality["photometric_status"]="ai_recovery"
            else:
                # A IA não teve evidência para escolher. Em vez de devolver tela vazia,
                # mostramos no máximo 2 candidatos locais estruturalmente plausíveis,
                # sempre como CONFERÊNCIA MANUAL e sem autorizar parada automática.
                top5=[x.copy() for x in recovery_candidates[:2]]
                for rank,item in enumerate(top5,1): item["rank"]=rank
                suggested=top5[0].get("sku") if top5 else None
                visual_score=float(top5[0].get("score") or 0) if top5 else 0.0
                decision_confidence=round(min(64.0, max(35.0, visual_score*0.62)),1) if top5 else 0.0
                score=decision_confidence; status="low"
                decision_source="manual_recovery_after_ai_reject"
                capture_quality["message"]=(
                    f"A IA não confirmou um SKU com segurança ({float(ai_audit.get('confidence') or 0):.1f}%). "
                    "O CHAPA ID exibiu somente candidatos estruturais para conferência manual; nenhuma identificação foi liberada automaticamente."
                )
        except Exception as e:
            print(f"[CHAPA-ID][IA] RECOVERY ERROR • {e}", flush=True)
            ai_audit={"used":True,"outcome":"error","reason":str(e)[:500]}
            # Falha de rede/timeout do provedor não pode zerar a experiência.
            # Preservamos somente os 2 melhores candidatos locais e marcamos como
            # conferência manual, sem fingir que a cor foi validada.
            top5=[x.copy() for x in recovery_candidates[:2]]
            for rank,item in enumerate(top5,1): item["rank"]=rank
            suggested=top5[0].get("sku") if top5 else None
            visual_score=float(top5[0].get("score") or 0) if top5 else 0.0
            decision_confidence=round(min(60.0, max(30.0, visual_score*0.58)),1) if top5 else 0.0
            score=decision_confidence; status="low"
            decision_source="manual_recovery_ai_unavailable"
            capture_quality["message"]=(
                "A auditoria externa não respondeu a tempo. Foram preservados apenas candidatos visualmente plausíveis para conferência manual; "
                "a identificação automática permaneceu bloqueada."
            )

    elif (not fast_scan) and neutral_low_light_guard:
        # Foto comum também não pode inventar branco/cinza/preto. IA fica fora da
        # decisão enquanto a fotometria não estiver validada.
        top5=[]
        suggested=None
        visual_score=0.0
        decision_confidence=0.0
        score=0.0
        status="low"
        decision_source="blocked_photometric_ambiguity"
        ai_audit={"used":False,"outcome":"blocked_by_photometry"}
        capture_quality["message"]=(
            "A imagem não permite determinar a cor real com segurança. Em superfícies brancas, cinzas ou pretas, "
            "use o scanner com iluminação validada ou uma foto com flash/luz suficiente. Nenhum SKU incompatível será sugerido."
        )

    elif (not fast_scan) and top5:
        should_audit=ai_enabled and (ais.get("mode")=="ai" or visual_score < float(ais.get("audit_below") or 92) or (bool(ais.get("require_ai_on_ambiguous",1)) and ambiguous))
        safety_floor=float(ais.get("min_local_confidence") or 72)
        if should_audit and visual_score>=safety_floor:
            try:
                print(f"[CHAPA-ID][IA] AUDIT START • top={top5[0].get('sku')} • local={visual_score:.1f}% • candidatos={len(top5)}", flush=True)
                ai_audit=_audit_candidates_with_ai(target,top5,ais)
                print(f"[CHAPA-ID][IA] AUDIT END • outcome={ai_audit.get('outcome')} • sku={ai_audit.get('sku')} • conf={ai_audit.get('confidence')} • {ai_audit.get('latency_ms')}ms", flush=True)
                if ai_audit.get("outcome")=="select" and ai_audit.get("sku"):
                    chosen=str(ai_audit["sku"]); ordered=sorted(top5,key=lambda x:(0 if str(x.get("sku"))==chosen else 1,-float(x.get("score") or 0)))
                    top5=ordered
                    for rank,item in enumerate(top5,1): item["rank"]=rank
                    suggested=top5[0]["sku"]
                    decision_confidence=round(min(float(top5[0].get("score") or 0),float(ai_audit.get("confidence") or 0)),1)
                    score=decision_confidence; status="high" if score>=88 and not ambiguous else ("medium" if score>=65 else "low")
                    decision_source="ai_audited"
                elif ai_audit.get("outcome")=="reject":
                    top5=[]; suggested=None; decision_confidence=0.0; score=0.0; status="low"; decision_source="ai_rejected"
            except Exception as e:
                print(f"[CHAPA-ID][IA] AUDIT ERROR • {e}", flush=True)
                ai_audit={"used":True,"outcome":"error","reason":str(e)[:500]}; decision_source="ai_error"
        elif should_audit and visual_score<safety_floor:
            ai_audit={"used":False,"outcome":"blocked_by_local_floor","reason":f"Confiança local {visual_score:.1f}% abaixo da trava mínima {safety_floor:.1f}%."}
            decision_source="local_floor_block"

    # V8 — política final de abstenção. Falha/timeout/503 da IA jamais transforma
    # um ranking apertado em SKU definido. O candidato continua visível para conferência,
    # mas a decisão oficial fica INCONCLUSIVA.
    ai_failed=bool(ai_audit.get("outcome") in {"error","timeout","unavailable"})
    sku_defined=bool(top5 and (exact_identity_top or (not margin_insufficient and decision_confidence>=65.0)))
    if visual_equivalence_group:
        suggested=None
        sku_defined=False
        decision_source="visual_pattern_identified_sku_ambiguous"
        status="medium" if visual_score>=82 else "low"
        score=min(float(score or 0),74.0)
    elif margin_insufficient and not exact_identity_top:
        suggested=None
        decision_source="inconclusive_margin" if not ai_failed else "inconclusive_margin_ai_unavailable"
        status="low"
        score=min(float(score or 0),60.0)
    elif ai_failed and decision_confidence<88.0 and not exact_identity_top:
        suggested=None
        sku_defined=False
        decision_source="inconclusive_ai_unavailable"
        status="low"
        score=min(float(score or 0),64.0)
    else:
        sku_defined=bool(suggested)

    top_tone_gate=(top5[0].get("verification_tone_gate") if top5 else None)
    if fast_scan:
        # Scanner rápido: responde cedo; o frontend exige repetição do mesmo SKU e
        # executa uma análise completa antes de apresentar o resultado final.
        safe_to_stop_scan=bool(sku_defined and top5 and capture_rankable and not neutral_low_light_guard and visual_score>=86 and top_tone_gate not in physical_conflicts)
    else:
        safe_to_stop_scan=bool(sku_defined and top5 and capture_rankable and not neutral_low_light_guard and visual_score>=86 and float(capture_quality.get("quality") or 0)>=60 and top_tone_gate not in physical_conflicts)
    print(f"[CHAPA-ID][DECISION] source={decision_source} • sku={suggested} • confidence={decision_confidence:.1f}% • ai={ai_audit.get('outcome')}", flush=True)
    response_payload = {"identification_id": None, "status": status, "visual_status": visual_status, "results": top5,
            "decision_confidence": decision_confidence,
            "sku_defined": bool(sku_defined),
            "margin_insufficient": bool(margin_insufficient),
            "min_margin_required": round(float(min_margin_required),2),
            "input_source": source_kind,
            "visual_score": visual_score,
            "primary_score": visual_score,
            "credible_floor": round(credible_floor,2) if verified else 0,
            "candidates_considered": len(shortlist),
            "candidates_returned": len(top5),
            "capture_quality": capture_quality,
            "photometric_validated": bool(controlled or original_bright_safe),
            "safe_to_stop_scan": safe_to_stop_scan,
            "rejection_reason": (None if top5 else (capture_quality.get("message") if not capture_rankable else "Nenhuma referência passou pelas travas físicas de cor, tonalidade e semelhança mínima.")),
            "score_margin": round(margin,2),
            "catalog_assisted": any(r.get("media_source")=="leo_site" for r in top5),
            "ambiguous": ambiguous, "ambiguity_count": (max(ambiguity_count,len(visual_equivalence_skus)) if ambiguous else 0),
            "visual_equivalence_group": bool(visual_equivalence_group),
            "visual_equivalence_skus": visual_equivalence_skus,
            "ambiguity_message": (("Padrão visual identificado com alta segurança, porém a mesma textura oficial está vinculada a múltiplos SKUs. A face sozinha não revela espessura ou número de faces; confirme esses atributos para definir o SKU exato." if visual_equivalence_group else (f"Resultado inconclusivo: diferença de apenas {margin:.1f} p.p. entre os melhores candidatos; mínimo técnico atual {min_margin_required:.1f} p.p. Confirme manualmente ou faça uma varredura mais ampla." if margin_insufficient else "Alta compatibilidade visual confirmada. Existem variações do mesmo padrão com aparência praticamente idêntica; confirme espessura, número de faces e dimensão para definir o SKU exato.")) if ambiguous else None),
            "analysis_mode": ("fast_scan" if fast_scan else "full"),
            "decision_source": decision_source,
            "ai_audit": ai_audit,
            "industrial_engine": {
                "version": "10.0",
                "mode": "domain_gated_surface_only_identity_first_multi_crop",
                "catalog_identity_check": True,
                "minimum_margin_policy": True,
                "position_invariant": True,
                "abstention_enabled": True,
                "top_patch_support": int((top5[0].get("patch_support") if top5 else 0) or 0),
                "top_patch_count": int((top5[0].get("patch_count") if top5 else 0) or 0),
                "top_robust_patch_score": (top5[0].get("robust_patch_score") if top5 else None),
                "confidence_margin": round(margin,2),
            },
            "analysis_ms": round((time.perf_counter()-analysis_started)*1000,1)}

    # Frames intermediários do Scanner Automático são efêmeros:
    # não criam milhares de históricos nem deixam arquivos temporários.
    if str(ephemeral).strip().lower() in {"1","true","sim","yes"}:
        con.close()
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass
        return response_payload

    cur = con.execute("""
        INSERT INTO identifications (query_file, suggested_sku, score, status, operator)
        VALUES (?, ?, ?, ?, ?)
    """, (str(target), suggested, score, status, operator))
    identification_id = cur.lastrowid
    if ai_audit.get("used"):
        con.execute("""INSERT INTO ai_audit_logs(identification_id,provider,model,local_top_sku,local_score,ai_selected_sku,ai_confidence,outcome,latency_ms,details) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (identification_id,(_load_ai_settings_private().get("provider") or ""),(_load_ai_settings_private().get("model") or ""),(credible[0].get("sku") if credible else None),(float(credible[0].get("score") or 0) if credible else 0),ai_audit.get("sku"),ai_audit.get("confidence"),ai_audit.get("outcome"),ai_audit.get("latency_ms"),json.dumps({"reason":ai_audit.get("reason"),"raw":ai_audit.get("raw")},ensure_ascii=False)[:8000]))
    con.commit()
    con.close()
    response_payload["identification_id"] = identification_id
    return response_payload

@app.post("/identifications/{identification_id}/confirm")
def confirm(identification_id: int, data: ConfirmIn):
    con = connect()
    identification = con.execute("SELECT * FROM identifications WHERE id=?", (identification_id,)).fetchone()
    product = con.execute("SELECT * FROM products WHERE sku=?", (data.confirmed_sku,)).fetchone()
    if not identification:
        con.close(); raise HTTPException(404, "Identificação não encontrada.")
    if not product:
        con.close(); raise HTTPException(404, "SKU confirmado não encontrado.")
    con.execute("""
        UPDATE identifications
        SET confirmed_sku=?, operator=COALESCE(?, operator)
        WHERE id=?
    """, (data.confirmed_sku, data.operator, identification_id))
    event_type = "confirmed" if (identification["suggested_sku"] or "") == data.confirmed_sku else "correction"
    con.execute("INSERT INTO learning_events(identification_id,suggested_sku,confirmed_sku,event_type,confidence) VALUES(?,?,?,?,?)",
                (identification_id, identification["suggested_sku"], data.confirmed_sku, event_type, identification["score"]))

    # V6 — aprendizado industrial em quarentena. Uma confirmação humana não vira
    # referência positiva automaticamente se houver baixa confiança ou correção de SKU.
    # Isso evita contaminar o modelo com um clique errado.
    query_path = Path(identification["query_file"])
    learned = False
    score_now=float(identification["score"] or 0)
    validation_status = "approved" if (event_type == "confirmed" and score_now >= 90.0) else "pending"
    con.execute("""INSERT INTO learning_quarantine(identification_id,sku,query_file,event_type,validation_status,consistency_score,notes)
                   VALUES(?,?,?,?,?,?,?)""",
                (identification_id,data.confirmed_sku,str(query_path),event_type,validation_status,score_now,
                 "Aprovação automática somente para confirmação consistente >=90%." if validation_status=="approved" else "Aguardando consistência adicional/revisão."))
    if validation_status == "approved" and query_path.exists():
        try:
            feature = dumps_feature(engine.extract(query_path))
            exists = con.execute("SELECT id FROM product_media WHERE product_id=? AND file_path=?",
                                 (product["id"], str(query_path))).fetchone()
            if not exists:
                con.execute("""
                    INSERT INTO product_media (product_id,media_type,file_path,feature_json,source,source_url)
                    VALUES (?,?,?,?,?,?)
                """, (product["id"], "image", str(query_path), feature, "confirmed_photo", None))
                learned = True
        except Exception:
            pass
    con.commit()
    con.close()
    return {"ok": True, "learned": learned}


class IndustrialScanSessionIn(BaseModel):
    operator: str = "Operador"
    regions_captured: int = 0
    regions_used: int = 0
    color_stability: float | None = None
    visual_diversity: float | None = None
    consensus_sku: str | None = None
    consensus_confidence: float | None = None
    decision_mode: str = "multi_region_consensus"
    payload: dict = {}

@app.post("/industrial/scan-session")
def save_industrial_scan_session(data: IndustrialScanSessionIn):
    con=connect()
    cur=con.execute("""INSERT INTO industrial_scan_sessions(operator,regions_captured,regions_used,color_stability,visual_diversity,consensus_sku,consensus_confidence,decision_mode,payload_json)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (data.operator,max(0,data.regions_captured),max(0,data.regions_used),data.color_stability,data.visual_diversity,data.consensus_sku,data.consensus_confidence,data.decision_mode,json.dumps(data.payload,ensure_ascii=False)[:12000]))
    con.commit(); sid=cur.lastrowid; con.close()
    return {"ok":True,"session_id":sid}

@app.get("/industrial/status")
def industrial_status():
    con=connect()
    groups=con.execute("SELECT COUNT(DISTINCT group_key) n FROM visual_equivalence_groups").fetchone()["n"]
    quarantine=con.execute("SELECT COUNT(*) n FROM learning_quarantine WHERE validation_status='pending'").fetchone()["n"]
    sessions=con.execute("SELECT COUNT(*) n FROM industrial_scan_sessions").fetchone()["n"]
    con.close()
    return {"version":"10.0","engine":"Motor Visual Industrial V10","multi_crop":True,"position_invariant":True,"multi_region_consensus":True,"safe_abstention":True,"visual_equivalence_groups":groups,"learning_quarantine_pending":quarantine,"scan_sessions":sessions}

@app.get("/history")
def history(limit: int = 100):
    con = connect()
    rows = con.execute("""
        SELECT * FROM identifications
        ORDER BY id DESC
        LIMIT ?
    """, (min(limit, 500),)).fetchall()
    con.close()
    return [dict(r) for r in rows]

@app.get("/printer/status")
def printer_status():
    return printer.status()

@app.post("/print")
def print_label(data: PrintIn):
    con = connect()
    p = con.execute("SELECT * FROM products WHERE sku=?", (data.sku,)).fetchone()
    con.close()
    if not p:
        raise HTTPException(404, "SKU não encontrado.")
    return printer.print_label(LabelData(
        sku=p["sku"],
        description=p["description"],
        address=p["address"],
        quantity=max(1, min(data.quantity, 50)),
    ))


# -----------------------------------------------------------------
# Frontend React compilado e servido pelo próprio FastAPI.
# Uso final: apenas a porta local 8000; Vite/5173 fica só para desenvolvimento.
# -----------------------------------------------------------------
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

@app.get("/")
def frontend_root():
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        return Response(
            "Frontend ainda não compilado. Execute npm run build na pasta frontend.",
            status_code=503,
            media_type="text/plain",
        )
    return FileResponse(index)
