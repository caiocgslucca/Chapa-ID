import getpass
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
TOOLS = ROOT / "tools"
CLOUDFLARED = TOOLS / "cloudflared.exe"
DOWNLOAD_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
ACCESS_FILE = ROOT / "ACESSO_CHAPA_ID.txt"
ONLINE_FILE = ROOT / "ENDERECO_ONLINE.txt"

def port_ready(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False

def find_free_port():
    # Faixa dedicada ao CHAPA ID. Se vários projetos estiverem rodando,
    # escolhe automaticamente a próxima porta disponível.
    for port in range(8100, 8201):
        if not port_ready(port):
            return port
    # Fallback do próprio Windows
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def install_cloudflared():
    # 1) Binário do próprio CHAPA ID
    if CLOUDFLARED.exists() and CLOUDFLARED.stat().st_size > 1_000_000:
        return

    # 2) Se o BI Operacional já tiver o mesmo cloudflared, reaproveita uma cópia.
    candidates = [
        Path(r"C:\Projetos\Operacional\tools\cloudflared.exe"),
        Path(r"C:\Projetos\Operacional\cloudflared.exe"),
    ]
    for source in candidates:
        try:
            if source.exists() and source.stat().st_size > 1_000_000:
                TOOLS.mkdir(exist_ok=True)
                import shutil
                shutil.copy2(source, CLOUDFLARED)
                print(f"Conector Cloudflare reutilizado de: {source}")
                return
        except Exception:
            pass

    TOOLS.mkdir(exist_ok=True)
    partial = CLOUDFLARED.with_suffix(".part")
    print("Baixando o conector seguro Cloudflare...")
    try:
        urllib.request.urlretrieve(DOWNLOAD_URL, partial)
        partial.replace(CLOUDFLARED)
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            "Não foi possível baixar cloudflared.exe. "
            "A rede da empresa pode ter bloqueado o download."
        ) from exc

def wait_server(process, port):
    for _ in range(160):
        if process.poll() is not None:
            raise RuntimeError("O servidor encerrou durante a inicialização.")
        if port_ready(port):
            return
        time.sleep(0.25)
    raise RuntimeError(f"O servidor não respondeu na porta {port}.")

def build_frontend():
    dist = FRONTEND / "dist"
    package_json = FRONTEND / "package.json"
    if not package_json.exists():
        raise RuntimeError("Frontend não encontrado.")

    npm_name = "npm.cmd" if os.name == "nt" else "npm"
    npm = shutil.which(npm_name) or shutil.which("npm")
    if not npm:
        raise RuntimeError(
            "Node.js/NPM não foi localizado. O CHAPA ID precisa do NPM somente para preparar a interface."
        )

    # IMPORTANTE: node_modules vindo dentro de ZIP pode existir, mas a pasta
    # node_modules/.bin (tsc.cmd, vite.cmd etc.) pode não sobreviver à compactação.
    # Nesse caso o antigo teste 'node_modules existe' dava falso positivo e o build
    # quebrava com: 'tsc não é reconhecido'. Validamos os executáveis reais.
    bin_dir = FRONTEND / "node_modules" / ".bin"
    tsc_bin = bin_dir / ("tsc.cmd" if os.name == "nt" else "tsc")
    vite_bin = bin_dir / ("vite.cmd" if os.name == "nt" else "vite")

    dependencies_ok = tsc_bin.exists() and vite_bin.exists()
    if not dependencies_ok:
        print("Componentes da interface incompletos. Reparando automaticamente...")
        print("Isso é feito apenas quando necessário e não exige configuração manual.")

        # npm install recria .bin mesmo quando node_modules já veio parcialmente no ZIP.
        r = subprocess.run(
            [npm, "install", "--include=dev", "--no-audit", "--no-fund"],
            cwd=FRONTEND,
        )
        if r.returncode:
            raise RuntimeError("Falha ao reparar os componentes do frontend com NPM.")

        if not (tsc_bin.exists() and vite_bin.exists()):
            # Segunda defesa: remove apenas node_modules quebrado e reconstrói pelo lock.
            print("Reparo rápido não foi suficiente. Reconstruindo dependências da interface...")
            broken_modules = FRONTEND / "node_modules"
            try:
                if broken_modules.exists():
                    shutil.rmtree(broken_modules)
            except Exception as exc:
                raise RuntimeError(
                    f"Não foi possível limpar node_modules incompleto: {exc}"
                ) from exc

            lock_file = FRONTEND / "package-lock.json"
            cmd = [npm, "ci", "--include=dev", "--no-audit", "--no-fund"] if lock_file.exists() else [npm, "install", "--include=dev", "--no-audit", "--no-fund"]
            r = subprocess.run(cmd, cwd=FRONTEND)
            if r.returncode or not (tsc_bin.exists() and vite_bin.exists()):
                raise RuntimeError(
                    "Não foi possível preparar TypeScript/Vite automaticamente. Verifique se o Node.js/NPM está disponível."
                )

    print("Compilando interface...")
    r = subprocess.run([npm, "run", "build"], cwd=FRONTEND)
    if r.returncode:
        raise RuntimeError("Falha ao compilar a interface.")

    if not (dist / "index.html").exists():
        raise RuntimeError("A compilação do frontend não gerou dist/index.html.")

def ensure_auth():
    # O CHAPA ID já possui serviço de autenticação próprio.
    code = "from app.services.auth import ensure_auth; ensure_auth()"
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND)
    if r.returncode:
        raise RuntimeError("Não foi possível preparar a autenticação.")

def wait_public_url(url: str, timeout: int = 90) -> bool:
    """Só libera o navegador quando DNS + túnel + origem responderem de verdade.

    Quick Tunnel pode imprimir a URL alguns segundos antes do DNS estar propagado.
    Abrir antes disso gera DNS_PROBE_FINISHED_NXDOMAIN e passa a impressão de falha
    do projeto. Aqui validamos resolução DNS e o endpoint público sem autenticação.
    """
    deadline = time.time() + timeout
    health = url.rstrip("/") + "/health-public"
    req_headers = {"User-Agent": "Mozilla/5.0 CHAPA-ID-Launcher"}
    host = urllib.parse.urlparse(url).hostname or ""
    last_status = 0.0
    while time.time() < deadline:
        now = time.time()
        dns_ok = False
        try:
            if host:
                socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                dns_ok = True
        except Exception:
            dns_ok = False

        if dns_ok:
            try:
                req = urllib.request.Request(health, headers=req_headers)
                with urllib.request.urlopen(req, timeout=4) as resp:
                    body = resp.read(2048).decode("utf-8", errors="ignore").lower()
                    if 200 <= getattr(resp, "status", 200) < 400 and "online" in body:
                        return True
            except Exception:
                pass

        if now - last_status >= 5:
            elapsed = int(timeout - max(0, deadline - now))
            print(f"Publicando endereço online... {elapsed}s • DNS={'OK' if dns_ok else 'aguardando'}")
            last_status = now
        time.sleep(1.0)
    return False

def read_access():
    if not ACCESS_FILE.exists():
        return None
    try:
        return ACCESS_FILE.read_text(encoding="utf-8")
    except Exception:
        return None

def main():
    if os.name != "nt":
        raise RuntimeError("Este iniciador é destinado ao Windows.")

    print("=" * 68)
    print("  CHAPA ID - ACESSO ONLINE GRATIS - CLOUDFLARE TUNNEL")
    print("=" * 68)
    print("Sem cartão, sem conta Cloudflare e sem liberação de porta no Windows.")
    print("Porta local automática para não conflitar com outros projetos.")
    print()

    port = find_free_port()
    print(f"Porta local selecionada automaticamente: {port}")

    install_cloudflared()
    build_frontend()
    ensure_auth()

    env = os.environ.copy()
    env["APP_HOST"] = "127.0.0.1"
    env["PORT"] = str(port)

    # FastAPI diretamente pelo Python do ambiente atual.
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=BACKEND,
        env=env,
    )

    tunnel = None
    try:
        wait_server(server, port)

        # Mesmo padrão do BI Operacional:
        # stdout + stderr juntos e leitura contínua da URL gerada.
        # Rede corporativa: usar HTTP/2 diretamente.
        # O modo automático tenta QUIC primeiro (UDP/7844) e pode ficar vários
        # segundos em timeout antes de cair para HTTP/2. Em ambientes Leo/empresa
        # isso gera a mensagem "Failed to dial a quic connection".
        # Forçamos HTTP/2 para evitar a tentativa QUIC e tornar o diagnóstico
        # determinístico. Cloudflare Tunnel ainda precisa de saída TCP/7844.
        tunnel = subprocess.Popen(
            [
                str(CLOUDFLARED),
                "tunnel",
                "--protocol",
                "http2",
                "--url",
                f"http://127.0.0.1:{port}",
                "--no-autoupdate",
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        opened = False
        assert tunnel.stdout is not None

        for line in tunnel.stdout:
            match = re.search(
                r"https://[a-z0-9-]+\.trycloudflare\.com",
                line,
                re.I,
            )

            if match and not opened:
                url = match.group(0)

                ONLINE_FILE.write_text(
                    url + "\n",
                    encoding="utf-8",
                )

                print()
                print("=" * 68)
                print("  CHAPA ID ONLINE")
                print("=" * 68)
                print()
                print("ENDEREÇO PARA CELULAR E NOTEBOOK:")
                print(url)
                print()
                print(f"Porta local utilizada: {port}")
                print()
                print("USUÁRIO E SENHA:")
                print(f"Abra: {ACCESS_FILE}")
                print()
                print("A URL também foi salva em ENDERECO_ONLINE.txt")
                print("Mantenha esta janela aberta.")
                print("Pressione CTRL+C para encerrar.")
                print("=" * 68)
                print()

                try:
                    import tkinter as tk
                    # Não depende do tkinter; bloco apenas não executa se indisponível.
                except Exception:
                    pass

                try:
                    import subprocess as _sp
                    _sp.run(
                        ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value '{url}'"],
                        stdout=_sp.DEVNULL,
                        stderr=_sp.DEVNULL,
                    )
                except Exception:
                    pass

                def open_when_ready():
                    print("Aguardando DNS, Cloudflare e CHAPA ID ficarem realmente disponíveis...")
                    ready = wait_public_url(url, timeout=90)
                    if ready:
                        print("Endereço online validado de ponta a ponta. Abrindo CHAPA ID...")
                        webbrowser.open(url)
                    else:
                        print("ATENÇÃO: o Quick Tunnel ainda não propagou. O navegador NÃO será aberto com endereço inválido.")
                        print("Mantenha esta janela aberta; copie o endereço acima e tente novamente em alguns segundos.")

                threading.Thread(target=open_when_ready, daemon=True).start()

                opened = True

            elif "7844" in line and ("ALLOW OUTBOUND" in line.upper() or "FAILED TO DIAL" in line.upper()):
                print(line.rstrip())
                print()
                print("[REDE BLOQUEADA] O CHAPA ID está funcionando localmente, mas esta rede bloqueou a saída do Cloudflare Tunnel.")
                print("Cloudflare exige conexão de saída TCP na porta 7844 quando usamos HTTP/2.")
                print("Nenhuma alteração de Firewall do Windows é necessária; o bloqueio é da rede/proxy corporativo.")
                print(f"Acesso local deste computador: http://127.0.0.1:{port}")
                print("Para acesso externo, conecte o computador a uma rede que permita TCP/7844 (ex.: outra rede/hotspot) ou peça liberação de saída à TI.")
                print()

            elif "ERR" in line.upper():
                print(line.rstrip())

        if tunnel.returncode:
            raise RuntimeError(
                "O túnel Cloudflare foi encerrado pela rede ou pelo antivírus."
            )

    finally:
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
        if server.poll() is None:
            server.terminate()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAcesso online encerrado.")
    except Exception as exc:
        print(f"\nERRO: {exc}")
        input("Pressione ENTER para fechar...")
        raise SystemExit(1)
