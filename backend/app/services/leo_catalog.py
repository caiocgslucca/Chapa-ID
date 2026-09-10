from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
from urllib.request import Request, urlopen
import html as html_lib
import json
import os
import re
import asyncio
import queue
import threading
import time

BASE_URL = "https://www.leomadeiras.com.br"
CATEGORY_URLS = [f"{BASE_URL}/categoria/mdf", f"{BASE_URL}/categoria/madeiras"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36"

@dataclass
class CatalogProduct:
    sku: str
    description: str
    product_url: str
    image_url: str | None = None
    manufacturer: str | None = None
    category: str | None = None

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self._href=None; self._parts=[]
    def handle_starttag(self, tag, attrs):
        if tag.lower()=="a": self._href=dict(attrs).get("href"); self._parts=[]
    def handle_data(self,data):
        if self._href is not None: self._parts.append(data)
    def handle_endtag(self,tag):
        if tag.lower()=="a" and self._href is not None:
            self.links.append((self._href," ".join("".join(self._parts).split())))
            self._href=None; self._parts=[]

def _fetch(url:str, timeout:int=35)->bytes:
    req=Request(url,headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml,application/json,image/avif,image/webp,image/*,*/*;q=0.8","Accept-Language":"pt-BR,pt;q=0.9","Cache-Control":"no-cache","Referer":BASE_URL+"/"})
    with urlopen(req,timeout=timeout) as r: return r.read()

def fetch_text(url:str)->str: return _fetch(url).decode("utf-8",errors="replace")

def _same_site(url:str)->bool:
    h=urlparse(url).netloc.lower(); return not h or h.endswith("leomadeiras.com.br")

def _clean_url(raw:str,base_url:str)->str|None:
    if not raw:return None
    raw=html_lib.unescape(raw).replace("\\/","/").strip().strip('"\'')
    if raw.startswith("//"):raw="https:"+raw
    absolute=urljoin(base_url,raw).split("#",1)[0]
    return absolute if _same_site(absolute) else None

def _clean_asset_url(raw:str,base_url:str)->str|None:
    if not raw:return None
    raw=html_lib.unescape(raw).replace("\\/","/").strip().strip('"\'')
    if raw.startswith("//"):raw="https:"+raw
    absolute=urljoin(base_url,raw).split("#",1)[0]
    return absolute if urlparse(absolute).scheme.lower() in {"http","https"} else None

def _is_product_url(url:str)->bool:
    path=unquote(urlparse(url).path).lower().rstrip("/")
    return bool(re.search(r"/p/\d+/[^/]+",path)) or "/produto/" in path or "/product/" in path

def discover_product_links(html:str,base_url:str)->list[str]:
    candidates=[]; parser=LinkParser()
    try: parser.feed(html); candidates.extend(h for h,_ in parser.links if h)
    except Exception: pass
    for pat in [r'''(?:href|data-href|productUrl|product_url|url|canonical)\s*[=:]\s*["']([^"']+)["']''',r'''["']((?:https?:)?(?:\\?/){1,2}[^"']*?/p/\d+/[^"'?#\\]+(?:\?[^"']*)?)["']''',r'''["'](/p/\d+/[^"'?#\\]+(?:\?[^"']*)?)["']''']:
        candidates.extend(m.group(1) for m in re.finditer(pat,html,re.I))
    out=[];seen=set()
    for raw in candidates:
        u=_clean_url(raw,base_url)
        if u and u not in seen and _is_product_url(u):seen.add(u);out.append(u)
    return out

def _walk_json(obj):
    if isinstance(obj,dict):
        yield obj
        for v in obj.values():yield from _walk_json(v)
    elif isinstance(obj,list):
        for v in obj:yield from _walk_json(v)

def _clean_text(v:str)->str: return " ".join(html_lib.unescape(re.sub(r"<[^>]+>"," ",v or "")).split())

def _valid_title(v:str|None)->bool:
    if not v:return False
    low=v.strip().lower()
    return len(v.strip())>=8 and low not in {"confirmar","adicionar ao carrinho","leo madeiras","comprar"}

def _extract_internal_code(html:str)->str|None:
    # REGRA OFICIAL DO PROJETO: SKU = "Cod. Interno" da página, nunca ID da URL/productID.
    pats=[
        r'C[oó]d(?:igo)?\.?\s*Interno\s*</?[^>]*>\s*([0-9]{4,})',
        r'C[oó]d(?:igo)?\.?\s*Interno[^0-9]{0,220}([0-9]{4,})',
        r'["\'](?:codigoInterno|codInterno|internalCode|internalSku)["\']\s*:\s*["\']?([0-9]{4,})',
    ]
    for pat in pats:
        m=re.search(pat,html,re.I|re.S)
        if m:return m.group(1)
    return None

def _extract_leo_code(html:str)->str|None:
    """Código comercial exibido pelo site no formato Cód. LM-....

    É usado somente quando a página realmente não possui Cod. Interno.
    Mantemos o prefixo LM- para não confundir com o SKU numérico oficial.
    """
    pats=[
        r'C[oó]d\.?\s*(LM-[A-Z0-9][A-Z0-9._/-]{1,})',
        r'\"(?:codigoLeo|codLeo|leoCode|sellerCode)\"\s*:\s*\"(LM-[A-Z0-9][A-Z0-9._/-]{1,})\"',
    ]
    for pat in pats:
        m=re.search(pat,html,re.I|re.S)
        if m:
            return m.group(1).upper().rstrip('.,;:')
    return None

def _extract_visible_title(html:str)->str|None:
    for pat in [r'<h1[^>]*>(.*?)</h1>',r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']']:
        m=re.search(pat,html,re.I|re.S)
        if m:
            t=_clean_text(m.group(1))
            if _valid_title(t) and "leo madeiras" not in t.lower():return t
    return None

def _infer_category(title:str)->str: return "MDF" if "mdf" in title.lower() else "Madeiras"

def parse_product_page(html:str,product_url:str)->CatalogProduct|None:
    # Captura primeiro os dois campos que o operador vê na página.
    internal_code=_extract_internal_code(html)
    visible_title=_extract_visible_title(html)
    json_product=None
    scripts=re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',html,re.I|re.S)
    for raw in scripts:
        try:data=json.loads(html_lib.unescape(raw.strip()))
        except Exception:continue
        for node in _walk_json(data):
            typ=node.get("@type")
            if typ=="Product" or (isinstance(typ,list) and "Product" in typ):json_product=node;break
        if json_product:break

    # IMPORTANTE: productID/ID do /p/ NÃO é SKU. Cod. Interno tem precedência absoluta.
    sku=internal_code
    # Algumas páginas do site não exibem Cod. Interno, mas exibem um identificador
    # comercial estável no mesmo produto, por exemplo: Cód. LM-FBSRR100800-A021.
    # Nesses casos ele vira a chave de fallback, mantendo o prefixo LM-.
    if not sku:
        sku=_extract_leo_code(html)
    if not sku and json_product:
        for key in ("sku","mpn"):
            raw=str(json_product.get(key) or "").strip()
            if re.fullmatch(r"LM-[A-Z0-9][A-Z0-9._/-]{1,}", raw, re.I):
                sku=raw.upper(); break
            digits=re.sub(r"\D","",raw)
            if len(digits)>=4:sku=digits;break

    title=visible_title
    if not title and json_product:
        candidate=_clean_text(str(json_product.get("name") or ""))
        if _valid_title(candidate):title=candidate

    image=None; brand=None
    if json_product:
        image=json_product.get("image")
        if isinstance(image,list):image=image[0] if image else None
        if isinstance(image,dict):image=image.get("url") or image.get("contentUrl")
        brand=json_product.get("brand")
        if isinstance(brand,dict):brand=brand.get("name")
    if not image:
        for pat in [r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',r'(https?://images\.cws\.digital/[^"\'<> ]+)']:
            m=re.search(pat,html,re.I|re.S)
            if m:image=m.group(1);break
    if not brand:
        for pat in [r'["\'](?:brand|manufacturer|fabricante)["\']\s*:\s*(?:\{[^{}]*?["\']name["\']\s*:\s*)?["\']([^"\']+)["\']',r'Fabricante\s*</?[^>]*>\s*([^<]{2,80})']:
            m=re.search(pat,html,re.I|re.S)
            if m:brand=_clean_text(m.group(1));break
    if sku and title:
        return CatalogProduct(sku=sku,description=title,product_url=product_url,image_url=_clean_asset_url(str(image),product_url) if image else None,manufacturer=str(brand).strip() if brand else None,category=_infer_category(title))
    return None


class RenderedProductSession:
    """Sessão persistente do navegador para ler os campos que o e-commerce renderiza via JavaScript.

    O ID presente em /p/<id>/ é apenas o identificador da página. O SKU oficial é sempre
    o valor visível após "Cod. Interno".
    """
    def __init__(self, timeout_ms: int = 45000):
        self.timeout_ms = timeout_ms
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            raise RuntimeError("Playwright não está instalado. Reabra o CHAPA ID pelo launcher.") from e
        browser_exe = _find_browser_executable()
        self._pw = sync_playwright().start()

        launch_kwargs = {
            "headless": True,
            "args": [
                "--disable-gpu",
                "--no-first-run",
                "--disable-background-networking",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        }

        if browser_exe:
            launch_kwargs["executable_path"] = browser_exe

        self._browser = self._pw.chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(
            user_agent=UA, locale="pt-BR", viewport={"width": 1440, "height": 1050}
        )
        self._page = self._context.new_page()
        return self

    def __exit__(self, exc_type, exc, tb):
        for obj, method in ((self._page, "close"), (self._context, "close"), (self._browser, "close")):
            try:
                if obj:
                    getattr(obj, method)()
            except Exception:
                pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    def fetch(self, product_url: str) -> CatalogProduct:
        page = self._page
        if page is None:
            raise RuntimeError("Sessão de navegador não inicializada.")

        # Retry isolado SEM herdar DOM do produto anterior. Esse caminho é usado
        # justamente quando a coleta paralela detecta possível SKU stale.
        try:
            page.goto("about:blank", wait_until="commit", timeout=4000)
        except Exception:
            pass
        page.goto(product_url, wait_until="domcontentloaded", timeout=self.timeout_ms)

        expected_tokens = _slug_tokens(product_url)
        title = None
        sku = None
        body_text = ""
        deadline = time.perf_counter() + min(self.timeout_ms / 1000.0, 22.0)
        while time.perf_counter() < deadline:
            try:
                h1 = page.locator("h1").first
                candidate = _clean_text(h1.inner_text(timeout=2500)) if h1.count() else ""
                normalized_title = _norm_match_text(candidate)
                hits = sum(1 for t in expected_tokens if t in normalized_title)
                if _valid_title(candidate) and (not expected_tokens or hits >= min(2, len(expected_tokens))):
                    code_data = page.evaluate(r"""() => {
                        const h1 = document.querySelector('h1');
                        if (!h1) return null;
                        // REGRA V4.1.5: o Cod. Interno só é aceito quando pertence ao MESMO
                        // bloco visual do H1 atual. Nunca usamos código solto de cards/recomendações.
                        let el = h1;
                        for (let i=0; i<8 && el; i++, el=el.parentElement) {
                            const st=getComputedStyle(el), r=el.getBoundingClientRect();
                            if(st.display==='none'||st.visibility==='hidden'||r.width<1||r.height<1) continue;
                            const t=(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
                            if(t.length > 2200) continue;
                            const internal=[...t.matchAll(/C[oó]d(?:igo)?\.?\s*Interno\s*(\d{4,})/ig)].map(m=>m[1]);
                            const lm=[...t.matchAll(/C[oó]d\.?\s*(LM-[A-Z0-9][A-Z0-9._\/-]{1,})/ig)].map(m=>m[1].toUpperCase());
                            const iu=[...new Set(internal)], lu=[...new Set(lm)];
                            if(iu.length===1) return {sku:iu[0], codeType:'internal', text:t, scope:'h1-ancestor'};
                            if(iu.length>1) return null;
                            if(lu.length===1) return {sku:lu[0], codeType:'leo', text:t, scope:'h1-ancestor'};
                            if(lu.length>1) return null;
                        }
                        // Fallback V4.1.7: alguns produtos de Madeiras exibem códigos LM curtos
                        // (ex.: LM-99, LM-983) e o código fica em um irmão visual do H1.
                        // Procuramos somente no painel principal que contém o H1, nunca no body inteiro.
                        let root=h1;
                        for(let i=0;i<10 && root?.parentElement;i++,root=root.parentElement){
                            const r=root.getBoundingClientRect();
                            const t=(root.innerText||root.textContent||'').replace(/\s+/g,' ').trim();
                            if(r.width<250 || r.height<120 || t.length>4500) continue;
                            const internal=[...t.matchAll(/C[oó]d(?:igo)?\.?\s*Interno\s*(\d{4,})/ig)].map(m=>m[1]);
                            const lm=[...t.matchAll(/C[oó]d\.?\s*(LM-[A-Z0-9][A-Z0-9._\/-]{1,})/ig)].map(m=>m[1].toUpperCase());
                            const iu=[...new Set(internal)], lu=[...new Set(lm)];
                            if(iu.length===1) return {sku:iu[0],codeType:'internal',text:t,scope:'product-panel'};
                            if(iu.length===0 && lu.length===1) return {sku:lu[0],codeType:'leo',text:t,scope:'product-panel'};
                        }
                        return null;
                    }""")
                    if code_data and code_data.get("sku"):
                        title = candidate
                        sku = str(code_data["sku"])
                        body_text = " ".join((page.locator("body").inner_text(timeout=3500) or "").split())
                        break
            except Exception:
                pass
            page.wait_for_timeout(180)

        if not sku:
            raise ValueError("Página renderizada sem Cod. Interno e sem Cód. LM visível no produto solicitado.")
        if not title:
            # Fallback pelo DOM final já renderizado.
            title = _extract_visible_title(page.content())
        if not title:
            raise ValueError(f"SKU {sku}: descrição do produto não encontrada após renderização.")

        final_html = page.content()
        parsed = parse_product_page(final_html, product_url)

        image_url = parsed.image_url if parsed else None
        manufacturer = parsed.manufacturer if parsed else None

        if not image_url:
            try:
                og = page.locator('meta[property="og:image"]')
                if og.count():
                    image_url = _clean_asset_url(og.first.get_attribute("content") or "", product_url)
            except Exception:
                pass

        # Fabricante aparece imediatamente antes do "Cód. LM" na oferta principal.
        if not manufacturer:
            m = re.search(r'([A-Za-zÀ-ÿ0-9 .&_-]{2,50})\s*\|\s*C[oó]d\.?\s*LM-[A-Z0-9][A-Z0-9._/-]{1,}', body_text, re.I)
            if m:
                manufacturer = _clean_text(m.group(1)).strip()

        return CatalogProduct(
            sku=sku,
            description=title,
            product_url=product_url,
            image_url=image_url,
            manufacturer=manufacturer,
            category=_infer_category(title),
        )


def fetch_rendered_product_isolated(product_url: str, timeout_ms: int = 32000) -> CatalogProduct:
    """Retry de segurança em navegador/contexto novos, sem estado SPA anterior."""
    with RenderedProductSession(timeout_ms=timeout_ms) as session:
        return session.fetch(product_url)


def _norm_match_text(value: str) -> str:
    """Normaliza texto para validar que o H1 renderizado pertence à URL atual."""
    import unicodedata
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", value).lower().split())


def _slug_tokens(product_url: str) -> list[str]:
    path = unquote(urlparse(product_url).path).rstrip("/")
    slug = path.split("/")[-1] if path else ""
    stop = {"mdf", "madeira", "madeiras", "face", "faces", "standard", "ultra", "premium", "mm", "com", "branca", "branco"}
    return [t for t in _norm_match_text(slug).split() if len(t) >= 4 and t not in stop][:6]


async def _extract_rendered_product_async(page, product_url: str, timeout_ms: int = 24000) -> CatalogProduct:
    """Lê o produto no DOM final e protege contra dados antigos de navegação SPA/cache."""
    # V4.1.3: zera o DOM antes de CADA produto. O site é SPA e foi observado o Cod. Interno
    # do produto anterior permanecer visível por alguns instantes mesmo com o H1 novo.
    # Uma navegação about:blank é barata e impede que esse estado seja aceito pelo coletor.
    try:
        await page.goto("about:blank", wait_until="commit", timeout=4000)
    except Exception:
        pass
    await page.goto(product_url, wait_until="commit", timeout=timeout_ms)

    expected_tokens = _slug_tokens(product_url)
    deadline = time.perf_counter() + min(timeout_ms / 1000.0, 15.0)
    data = None
    while time.perf_counter() < deadline:
        try:
            data = await page.evaluate(r'''() => {
                const h1 = document.querySelector('h1');
                if (!h1) return null;
                const title = (h1.innerText || h1.textContent || '').replace(/\s+/g,' ').trim();
                // REGRA V4.1.5: primeiro encontra o bloco do produto atual pelo H1 e
                // só então lê o Cod. Interno dentro desse mesmo bloco.
                let boxText = '';
                let el = h1;
                for (let i=0; i<8 && el; i++, el=el.parentElement) {
                    const st=getComputedStyle(el); const r=el.getBoundingClientRect();
                    if(st.display==='none'||st.visibility==='hidden'||r.width<1||r.height<1) continue;
                    const t=(el.innerText||'').replace(/\s+/g,' ').trim();
                    if(t.length>2200) continue;
                    const internal=[...t.matchAll(/C[oó]d(?:igo)?\.?\s*Interno\s*(\d{4,})/ig)].map(m=>m[1]);
                    const lm=[...t.matchAll(/C[oó]d\.?\s*(LM-[A-Z0-9][A-Z0-9._\/-]{1,})/ig)].map(m=>m[1].toUpperCase());
                    const iu=[...new Set(internal)], lu=[...new Set(lm)];
                    if(iu.length===1 || (iu.length===0 && lu.length===1)){ boxText=t; break; }
                    if(iu.length>1 || lu.length>1){ boxText=''; break; }
                }
                // Produtos de Madeiras podem usar Cód. LM curto (LM-99/LM-983)
                // em um irmão do H1. Amplia apenas até o painel principal do produto.
                if(!boxText){
                    let root=h1;
                    for(let i=0;i<10 && root?.parentElement;i++,root=root.parentElement){
                        const r=root.getBoundingClientRect();
                        const t=(root.innerText||'').replace(/\s+/g,' ').trim();
                        if(r.width<250 || r.height<120 || t.length>4500) continue;
                        const internal=[...t.matchAll(/C[oó]d(?:igo)?\.?\s*Interno\s*(\d{4,})/ig)].map(m=>m[1]);
                        const lm=[...t.matchAll(/C[oó]d\.?\s*(LM-[A-Z0-9][A-Z0-9._\/-]{1,})/ig)].map(m=>m[1].toUpperCase());
                        const iu=[...new Set(internal)], lu=[...new Set(lm)];
                        if(iu.length===1 || (iu.length===0 && lu.length===1)){boxText=t;break;}
                    }
                }
                const m = boxText.match(/C[oó]d(?:igo)?\.?\s*Interno\s*(\d{4,})/i);
                const lm = boxText.match(/C[oó]d\.?\s*(LM-[A-Z0-9][A-Z0-9._\/-]{1,})/i);
                const brand = boxText.match(/([A-Za-zÀ-ÿ0-9 .&_-]{2,50})\s*\|\s*C[oó]d\.?\s*LM-[A-Z0-9][A-Z0-9._\/-]{1,}/i);
                const og = document.querySelector('meta[property="og:image"]')?.getAttribute('content') || '';
                return {title, sku: m ? m[1] : (lm ? lm[1].toUpperCase() : ''), codeType: m ? 'internal' : (lm ? 'leo' : ''), manufacturer: brand ? brand[1].trim() : '', image: og};
            }''')
        except Exception:
            data = None
        if data and data.get("sku") and _valid_title(_clean_text(data.get("title") or "")):
            normalized_title = _norm_match_text(data.get("title") or "")
            hits = sum(1 for t in expected_tokens if t in normalized_title)
            if not expected_tokens or hits >= min(2, len(expected_tokens)):
                break
        await page.wait_for_timeout(120)
    if not data or not data.get("sku"):
        raise ValueError("Página renderizada sem Cod. Interno e sem Cód. LM visível.")
    title = _clean_text(data.get("title") or "")
    if not _valid_title(title):
        raise ValueError(f"SKU {data.get('sku')}: descrição do produto não encontrada após renderização.")
    normalized_title = _norm_match_text(title)
    hits = sum(1 for t in expected_tokens if t in normalized_title)
    if expected_tokens and hits < min(2, len(expected_tokens)):
        raise ValueError("Página renderizada não estabilizou no produto solicitado; coleta protegida contra SKU incorreto.")

    image_url = _clean_asset_url(str(data.get("image") or ""), product_url) or None
    manufacturer = _clean_text(str(data.get("manufacturer") or "")) or None
    if not image_url or not manufacturer:
        final_html = await page.content()
        parsed = parse_product_page(final_html, product_url)
        if parsed:
            image_url = image_url or parsed.image_url
            manufacturer = manufacturer or parsed.manufacturer
    return CatalogProduct(
        sku=str(data["sku"]), description=title, product_url=product_url,
        image_url=image_url, manufacturer=manufacturer, category=_infer_category(title)
    )


def iter_rendered_products_parallel(product_urls: list[str], workers: int = 20, timeout_ms: int = 18000):
    """Coleta paralela com um navegador e várias páginas; o banco fica serial na thread principal."""
    browser_exe = _find_browser_executable()
    workers = max(1, min(int(workers or 1), 20))
    out_q: queue.Queue = queue.Queue(maxsize=max(32, workers * 8))
    sentinel = object()

    async def producer():
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                # Divide a coleta entre 2 processos de navegador. Em um único Chromium,
                # muitas páginas podem disputar o mesmo pool de rede do host e a vazão
                # deixa de crescer mesmo aumentando as abas. Dois processos mantêm o
                # fluxo isolado sem transformar a máquina em uma fazenda de browsers.
                browser_count = 2 if workers >= 12 else 1
                browsers = []
                contexts = []
                for _ in range(browser_count):
                    launch_kwargs = {
                        "headless": True,
                        "args": [
                            "--disable-gpu",
                            "--no-first-run",
                            "--disable-background-networking",
                            "--disable-extensions",
                            "--disable-sync",
                            "--disable-component-update",
                            "--disable-default-apps",
                            "--disable-features=Translate,BackForwardCache",
                            "--no-sandbox",
                            "--disable-dev-shm-usage",
                        ],
                    }

                    if browser_exe:
                        launch_kwargs["executable_path"] = browser_exe

                    browser = await p.chromium.launch(**launch_kwargs)
                    context = await browser.new_context(
                        user_agent=UA, locale="pt-BR", viewport={"width":1100,"height":760},
                        service_workers="block"
                    )
                    browsers.append(browser); contexts.append(context)

                # V2.9 ANTI-TRAVAMENTO:
                # A V2.8 preenchia uma fila limitada ANTES de iniciar os workers.
                # Com 5.325 URLs a fila atingia o maxsize (~80) e o producer ficava
                # bloqueado em await in_q.put(), enquanto nenhum worker ainda existia
                # para consumir. Resultado: leitura 100%, coleta 0% indefinidamente.
                # Agora os workers iniciam primeiro e um feeder independente alimenta
                # a fila com backpressure real, sem carregar tudo em memória.
                in_q: asyncio.Queue = asyncio.Queue(maxsize=max(64, workers * 4))

                async def feeder():
                    for idx, url in enumerate(product_urls, start=1):
                        await in_q.put((idx, url))
                    for _ in range(workers):
                        await in_q.put(None)

                async def worker(worker_id: int):
                    context = contexts[worker_id % browser_count]
                    page = await context.new_page()
                    async def route_handler(route):
                        try:
                            # Mantemos JS/XHR. Cortamos apenas peso visual.
                            if route.request.resource_type in {"image", "font", "media", "stylesheet"}:
                                await route.abort()
                            else:
                                await route.continue_()
                        except Exception:
                            pass
                    await page.route("**/*", route_handler)

                    # Evita 20 navegações explodirem no mesmo milissegundo.
                    await page.wait_for_timeout((worker_id % 10) * 110)

                    while True:
                        task = await in_q.get()
                        if task is None:
                            break
                        idx, url = task
                        t0 = time.perf_counter()
                        item = None
                        err = None

                        # V3.1: erro transitório não vira erro de negócio imediatamente.
                        # Tentativa 1 = rápida; tentativa 2 = nova navegação com janela
                        # um pouco maior. Só depois disso o produto entra na lista de erros.
                        last_exc = None
                        for attempt in (1, 2):
                            try:
                                effective_timeout = timeout_ms if attempt == 1 else max(timeout_ms, 24000)
                                item = await _extract_rendered_product_async(page, url, timeout_ms=effective_timeout)
                                err = None
                                break
                            except Exception as e:
                                last_exc = e
                                if attempt == 1:
                                    try:
                                        await page.wait_for_timeout(450 + (worker_id % 4) * 90)
                                    except Exception:
                                        pass
                                    # limpa DOM/cache visual da tentativa que falhou,
                                    # sem criar uma sessão nova.
                                    try:
                                        await page.goto("about:blank", wait_until="commit", timeout=4000)
                                    except Exception:
                                        pass
                        if item is None:
                            err = f"Falhou após 2 tentativas: {last_exc}"
                        out_q.put((idx, url, item, err, time.perf_counter()-t0))
                    try:
                        await page.close()
                    except Exception:
                        pass

                worker_tasks = [asyncio.create_task(worker(i)) for i in range(workers)]
                feeder_task = asyncio.create_task(feeder())
                await asyncio.gather(feeder_task, *worker_tasks)
                for context in contexts:
                    try: await context.close()
                    except Exception: pass
                for browser in browsers:
                    try: await browser.close()
                    except Exception: pass
        except Exception as e:
            out_q.put((0, "", None, f"Falha no pool de coleta: {e}", 0.0))
        finally:
            out_q.put(sentinel)

    def runner():
        asyncio.run(producer())

    th = threading.Thread(target=runner, name="chapa-id-leo-parallel", daemon=True)
    th.start()
    while True:
        value = out_q.get()
        if value is sentinel:
            break
        if value[0] == 0 and value[3]:
            raise RuntimeError(value[3])
        yield value
    th.join(timeout=2)

def download_image(url:str,target:Path)->None:
    target.parent.mkdir(parents=True,exist_ok=True); raw=_fetch(url,timeout=35)
    if len(raw)<500:raise ValueError("Imagem recebida está vazia ou inválida.")
    target.write_bytes(raw)

def _find_browser_executable() -> str | None:
    # 1. Caminho configurado manualmente
    env_browser = os.environ.get("CHAPA_ID_BROWSER")
    if env_browser and Path(env_browser).exists():
        return env_browser

    # 2. Windows - mantém funcionamento atual
    windows_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(
            r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"
        ),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
        ),
    ]

    for candidate in windows_candidates:
        if candidate and Path(candidate).exists():
            return candidate

    # 3. Linux / Railway - Chromium do sistema
    linux_candidates = [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ]

    for candidate in linux_candidates:
        if Path(candidate).exists():
            return candidate

    # 4. Chromium instalado pelo Playwright no Docker
    playwright_roots = [
        Path("/ms-playwright"),
        Path.home() / ".cache" / "ms-playwright",
    ]

    for root in playwright_roots:
        if not root.exists():
            continue

        patterns = [
            "chromium-*/chrome-linux/chrome",
            "chromium-*/chrome-linux64/chrome",
            "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
            "chromium_headless_shell-*/chrome-linux/headless_shell",
        ]

        for pattern in patterns:
            matches = sorted(root.glob(pattern))

            if matches:
                return str(matches[-1])

    return None

def _parse_expected_count(text:str)->int:
    """Lê o total oficial exibido pelo site, tolerando ponto/espaço como milhar."""
    if not text:
        return 0
    patterns = [
        r'([0-9][0-9\.\s]{0,12})\s+produtos\s+encontrados(?:\s+para\s+voc[eê])?',
        r'produtos\s+encontrados[^0-9]{0,20}([0-9][0-9\.\s]{0,12})',
        r'([0-9][0-9\.\s]{2,12})\s+produtos\b',
        r'produtos[^0-9]{0,35}([0-9][0-9\.\s]{2,12})',
    ]
    for pat in patterns:
        m=re.search(pat,text,re.I)
        if m:
            raw=re.sub(r'\D','',m.group(1))
            if raw:
                try:
                    value=int(raw)
                    if value>0:
                        return value
                except Exception:
                    pass
    return 0

def _category_expected_count(category_url:str)->int:
    try:
        return _parse_expected_count(fetch_text(category_url))
    except Exception:
        return 0

def _browser_discover_category(
    category_url: str,
    max_pages: int = 250,
    delay_seconds: float = .25,
    progress_callback=None
) -> list[str]:
    """Percorre a paginação da Leo com diagnóstico adicional para Railway/Linux."""

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError(
            "Playwright não está instalado. Reabra pelo launcher."
        ) from e

    browser_exe = _find_browser_executable()

    expected = _category_expected_count(category_url)
    found = []
    seen = set()
    page_counts = {}

    max_pages = max(1, min(int(max_pages or 250), 260))
    expected_pages = ((expected + 23) // 24) if expected else max_pages
    target_pages = min(max_pages, max(expected_pages, 1))

    with sync_playwright() as p:
        launch_kwargs = {
            "headless": True,
            "args": [
                "--disable-gpu",
                "--no-first-run",
                "--disable-background-networking",
                "--disable-extensions",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        }

        if browser_exe:
            launch_kwargs["executable_path"] = browser_exe

        browser = p.chromium.launch(**launch_kwargs)

        context = browser.new_context(
            user_agent=UA,
            locale="pt-BR",
            viewport={"width": 1280, "height": 820},
            service_workers="block",
        )

        page = context.new_page()

        def route_handler(route):
            try:
                if route.request.resource_type in {"image", "font", "media"}:
                    route.abort()
                else:
                    route.continue_()
            except BaseException:
                pass

        page.route("**/*", route_handler)

        def close_popups():
            for txt in [
                "Aceitar e fechar",
                "Confirmar",
                "Fechar",
            ]:
                try:
                    loc = page.get_by_text(txt, exact=True)

                    if loc.count() and loc.first.is_visible():
                        loc.first.click(timeout=900)
                        page.wait_for_timeout(180)

                except Exception:
                    pass

        def open_category():
            page.goto(
                category_url,
                wait_until="domcontentloaded",
                timeout=90000,
            )

            page.wait_for_timeout(650)
            close_popups()

        def diagnostic():
            try:
                page.wait_for_timeout(2500)

                diag_url = page.url

                try:
                    diag_title = page.title()
                except Exception:
                    diag_title = ""

                try:
                    diag_text = page.locator("body").inner_text(
                        timeout=5000
                    )
                except Exception:
                    diag_text = ""

                try:
                    diag_html = page.content()
                except Exception:
                    diag_html = ""

                try:
                    diag_links = page.locator(
                        'a[href*="/p/"]'
                    ).count()
                except Exception:
                    diag_links = -1

                print(
                    "[CHAPA ID] [DIAGNOSTICO CATALOGO] "
                    f"categoria={category_url} | "
                    f"url_final={diag_url} | "
                    f"titulo={diag_title!r} | "
                    f"links_produto={diag_links} | "
                    f"html={len(diag_html)} bytes | "
                    f"texto={len(diag_text)} chars",
                    flush=True,
                )

                resumo = " ".join(
                    diag_text.split()
                )[:1200]

                print(
                    "[CHAPA ID] [DIAGNOSTICO CATALOGO] "
                    f"CONTEUDO={resumo!r}",
                    flush=True,
                )

            except Exception as diag_error:
                print(
                    "[CHAPA ID] [DIAGNOSTICO CATALOGO] "
                    f"ERRO={diag_error!r}",
                    flush=True,
                )

        open_category()
        diagnostic()

        # O total oficial costuma estar apenas no DOM renderizado.
        try:
            rendered_text = page.locator(
                "body"
            ).inner_text(timeout=5000)

            rendered_expected = _parse_expected_count(
                rendered_text
            )

            if rendered_expected > 0:
                expected = max(
                    expected,
                    rendered_expected,
                )

                expected_pages = (
                    (expected + 23) // 24
                )

                target_pages = min(
                    max_pages,
                    max(expected_pages, 1),
                )

        except Exception:
            pass

        def current_hrefs():
            try:
                page.evaluate(
                    "window.scrollTo("
                    "0, document.body.scrollHeight * 0.86)"
                )

                page.wait_for_timeout(150)

            except Exception:
                pass

            try:
                hrefs = page.locator(
                    'a[href*="/p/"]'
                ).evaluate_all(
                    "els => "
                    "els.map(e => e.href)"
                    ".filter(Boolean)"
                )

            except Exception:
                hrefs = []

            clean = []
            local_seen = set()

            for href in hrefs:
                u = _clean_url(
                    href,
                    category_url,
                )

                if (
                    u
                    and _is_product_url(u)
                    and u not in local_seen
                ):
                    local_seen.add(u)
                    clean.append(u)

            return clean

        def collect_current(
            page_no: int,
            emit: bool = True
        ):
            hrefs = current_hrefs()

            before = len(found)
            new_urls = []

            for clean in hrefs:
                if clean not in seen:
                    seen.add(clean)
                    found.append(clean)
                    new_urls.append(clean)

            added = len(found) - before

            page_counts[page_no] = max(
                page_counts.get(page_no, 0),
                added,
            )

            if emit and progress_callback:
                progress_callback({
                    "category": (
                        category_url
                        .rsplit("/", 1)[-1]
                        .upper()
                    ),
                    "page": page_no,
                    "found": len(found),
                    "expected": expected,
                    "new": added,
                    "new_urls": new_urls,
                })

            return added

        def click_exact_page(
            target: int,
            force: bool = False
        ) -> bool:
            try:
                num = page.get_by_text(
                    str(target),
                    exact=True,
                )

                for i in range(
                    num.count() - 1,
                    -1,
                    -1,
                ):
                    el = num.nth(i)

                    try:
                        if (
                            el.is_visible()
                            and el.evaluate(
                                "e => !!e.closest("
                                "'a,button,li')"
                            )
                        ):
                            el.click(
                                timeout=5000,
                                force=force,
                            )

                            return True

                    except Exception:
                        pass

            except Exception:
                pass

            return False

        def click_window_arrow() -> bool:
            try:
                arrows = page.locator(
                    'a:has-text("»"), '
                    'button:has-text("»"), '
                    'a:has-text("›"), '
                    'button:has-text("›")'
                )

                for i in range(
                    arrows.count() - 1,
                    -1,
                    -1,
                ):
                    a = arrows.nth(i)

                    try:
                        if (
                            a.is_visible()
                            and a.get_attribute(
                                "aria-disabled"
                            ) != "true"
                        ):
                            a.click(
                                timeout=5000,
                                force=True,
                            )

                            page.wait_for_timeout(300)
                            return True

                    except Exception:
                        pass

            except Exception:
                pass

            return False

        def normal_navigate(
            target: int
        ) -> bool:
            if click_exact_page(target):
                return True

            if click_window_arrow():
                page.wait_for_timeout(250)

                if click_exact_page(
                    target,
                    force=True,
                ):
                    return True

            for retry in range(4):
                page.wait_for_timeout(
                    350 + retry * 250
                )

                if click_exact_page(
                    target,
                    force=True,
                ):
                    return True

            return False

        def hard_recover_to(
            target: int
        ) -> bool:
            try:
                open_category()

                hops = (
                    max(target, 1) - 1
                ) // 10

                for _ in range(hops):
                    if not click_window_arrow():
                        return False

                page.wait_for_timeout(220)

                if target == 1:
                    return True

                return click_exact_page(
                    target,
                    force=True,
                )

            except Exception:
                return False

        # Página 1
        collect_current(1)

        # Demais páginas
        page_no = 2

        while page_no <= target_pages:
            moved = normal_navigate(page_no)

            if not moved:
                moved = hard_recover_to(page_no)

            if not moved:
                break

            page.wait_for_timeout(
                max(
                    120,
                    int(delay_seconds * 1000),
                )
            )

            added = collect_current(
                page_no
            )

            # Se navegou mas não trouxe produto novo,
            # tenta reconstruir a navegação.
            if added <= 0:
                recovered = hard_recover_to(
                    page_no
                )

                if recovered:
                    page.wait_for_timeout(500)

                    added = collect_current(
                        page_no
                    )

            if added <= 0:
                # Diagnóstico adicional se a paginação travar
                diagnostic()

            page_no += 1

        try:
            context.close()
        except Exception:
            pass

        try:
            browser.close()
        except Exception:
            pass

    return found

def discover_catalog_links(max_pages:int=250,delay_seconds:float=.25,progress_callback=None)->tuple[list[str],int]:
    # MDF e Madeiras são catálogos independentes. Varremos os dois em paralelo para
    # cortar praticamente pela metade a fase 1 sem alterar a lógica de paginação.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    expected_by_url={u:_category_expected_count(u) for u in CATEGORY_URLS}
    expected_total=sum(expected_by_url.values())
    progress_lock=threading.Lock()
    category_progress={u:0 for u in CATEGORY_URLS}
    category_expected={u:int(expected_by_url.get(u) or 0) for u in CATEGORY_URLS}
    global_unique_seen=set()

    def run_category(idx:int, category_url:str):
        local_seen=set(); local=[]
        try:
            direct=discover_product_links(fetch_text(category_url),category_url)
        except Exception:
            direct=[]
        for u in direct:
            if u not in local_seen:
                local_seen.add(u); local.append(u)
        def cb(info):
            with progress_lock:
                category_progress[category_url]=max(category_progress[category_url],int(info.get("found") or 0))
                category_expected[category_url]=max(category_expected[category_url],int(info.get("expected") or 0))
                for u in info.get("new_urls") or []:
                    global_unique_seen.add(u)
                global_scanned=sum(category_progress.values())
                global_expected_units=sum(category_expected.values())
                global_unique_found=len(global_unique_seen)
            if progress_callback:
                payload={k:v for k,v in info.items() if k!="new_urls"}
                progress_callback({**payload,"category_index":idx,"categories":len(CATEGORY_URLS),
                                   "global_found":global_unique_found,
                                   "global_unique_found":global_unique_found,
                                   "global_scanned":global_scanned,
                                   "global_expected":global_expected_units})
        browser=_browser_discover_category(category_url,max_pages,delay_seconds,cb)
        for u in browser:
            if u not in local_seen:
                local_seen.add(u); local.append(u)
        return idx, local

    results=[]
    with ThreadPoolExecutor(max_workers=len(CATEGORY_URLS), thread_name_prefix="chapa-scan") as pool:
        futs=[pool.submit(run_category, idx, url) for idx,url in enumerate(CATEGORY_URLS)]
        for fut in as_completed(futs):
            results.append(fut.result())

    seen=set(); out=[]
    for _, items in sorted(results, key=lambda x:x[0]):
        for u in items:
            if u not in seen:
                seen.add(u); out.append(u)
    if not out:raise RuntimeError("Nenhum produto real foi localizado nas categorias MDF e Madeiras.")
    final_expected_units=sum(int(category_expected.get(u) or 0) for u in CATEGORY_URLS)
    return out,final_expected_units

def iter_catalog(max_pages:int=180,delay_seconds:float=.25):
    links,_=discover_catalog_links(max_pages,delay_seconds)
    yield from links
