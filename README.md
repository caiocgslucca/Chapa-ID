# CHAPA ID — V1

MVP funcional para identificação visual de chapas.

## O que já existe
- Frontend React + TypeScript + Vite
- Backend FastAPI + SQLite
- Importação CSV/XLSX de SKU, descrição e endereço
- Cadastro de produto
- Cadastro visual por múltiplas fotos
- Upload de vídeo
- Consulta por foto
- Top 3 resultados com score
- Confirmação/correção do operador
- Histórico de identificações
- Dashboard básico
- Adaptador de impressão preparado para receber a lógica do projeto CS
- Estrutura VisionEngine desacoplada para trocar o mecanismo de reconhecimento depois

## Como executar no Windows

### 1. Backend
Abra PowerShell na pasta `backend`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Frontend
Abra outro PowerShell na pasta `frontend`:

```powershell
npm install
npm run dev -- --host 0.0.0.0
```

Depois abra:
- Frontend: http://localhost:5173
- API: http://localhost:8000/docs

## Observação sobre reconhecimento
A V1 usa um mecanismo visual local leve baseado em características de cor + textura para deixar o fluxo já funcional.
A arquitetura está preparada para trocar por DINOv2 / SigLIP / CLIP / modelo próprio sem alterar o restante do app.

## Impressão
O arquivo `backend/app/services/printing.py` contém a interface preparada.
Para ficar idêntico ao projeto CS, substitua a implementação pelo mesmo comando/driver/modelo utilizado naquele projeto.


## V1.1 — Importação e acesso pelo celular

### Importação
A importação agora possui:
- barra de progresso de 0 a 100%
- quantidade processada / total
- data e hora de início
- data e hora de fim
- duração
- contagem de novos, atualizados e erros
- processamento em lote com UPSERT para melhorar performance
- SQLite em WAL + índices

### Celular
A API deixou de usar `localhost:8000` fixo. Agora o frontend usa automaticamente o mesmo IP usado para abrir o site.

Execute **uma vez** `configurar_rede_celular.bat` como Administrador para liberar as portas 5173 e 8000 no Firewall do Windows.

Depois:
1. Deixe `executar_backend.bat` aberto.
2. Deixe `executar_frontend.bat` aberto.
3. Confirme que celular e notebook estão na mesma rede.
4. Abra no celular `http://IP_DO_NOTEBOOK:5173`.

Se ainda ocorrer `ERR_CONNECTION_REFUSED`, confira se a rede do Windows está como **Privada** e se a rede Wi-Fi não possui isolamento entre dispositivos.


# V1.2 — HTTPS no celular sem Administrador

A V1.2 usa um **Cloudflare Quick Tunnel** apenas para teste.

Arquitetura:

Celular / navegador
→ HTTPS `*.trycloudflare.com`
→ conexão de saída do notebook
→ `cloudflared` em modo usuário
→ `127.0.0.1:8000`
→ FastAPI + React
→ SQLite / reconhecimento / impressão

## Não faz
- Não cria regra de Firewall.
- Não abre porta de entrada.
- Não instala serviço do Windows.
- Não exige execução como Administrador.
- Não publica o banco diretamente na internet.

## Proteção
- Login obrigatório para acessar APIs e dados.
- Senha aleatória criada na primeira execução.
- Cookie de sessão `HttpOnly`.
- Cookie `Secure`, utilizado através do endereço HTTPS.
- Sessão de 12 horas.
- A URL pública aleatória muda a cada execução.

## Como executar
Use apenas:

`EXECUTAR_CHAPA_ID.bat`

Na primeira execução o projeto:
1. instala dependências no `.venv` local;
2. compila o React;
3. cria usuário/senha;
4. baixa `cloudflared.exe` para a pasta local `tools`;
5. sobe o CHAPA ID somente em `127.0.0.1:8000`;
6. abre um Quick Tunnel HTTPS;
7. mostra e copia a URL pública.

A senha fica no arquivo local:

`ACESSO_CHAPA_ID.txt`

Não compartilhe esse arquivo junto com a URL.

## Observação corporativa
O método não altera configurações administrativas, mas a rede/EDR da empresa ainda pode bloquear o download ou a conexão de saída do `cloudflared`. Se isso acontecer, o projeto encerra sem alterar o Firewall e o arquivo `tunel.log` informa a falha.


## V1.2.1 — Correção do launcher Python
O launcher não depende mais do comando `py`.

Agora ele procura automaticamente:
- `.venv\Scripts\python.exe` existente
- `python`
- `python3`
- instalações Python comuns em `%LOCALAPPDATA%`
- instalações comuns em `Program Files`

Também foi incluído `DIAGNOSTICO_PYTHON.bat`.


## V1.2.2 — Compatibilidade TypeScript/Vite
Corrigido `moduleResolution` de `Node` para `Bundler`, compatível com as versões atuais do TypeScript e Vite.


## V1.2.3 — Tipagens Vite/CSS
Adicionados `src/vite-env.d.ts` e `src/global.d.ts` para o TypeScript reconhecer imports de CSS e assets durante `npm run build`.
Também foi incluído `types: ["vite/client"]` no `tsconfig.json`.


## V1.2.4 — Correção do túnel no PowerShell
Corrigido erro do `Start-Process` ao usar o mesmo arquivo para `RedirectStandardOutput` e `RedirectStandardError`.

Agora o launcher usa:
- `tunel_out.log`
- `tunel_err.log`

A URL `https://*.trycloudflare.com` é procurada nos dois arquivos automaticamente.


## V1.4 — Mesmo Cloudflare do BI Operacional

O modo online foi refeito usando o mesmo padrão encontrado no projeto
`Acompanhamento_Operacional_V17_Online_Gratis_Sem_Cartao`:

- `online_launcher.py`
- Cloudflare Quick Tunnel
- `cloudflared tunnel --url http://127.0.0.1:PORT --no-autoupdate`
- leitura da URL diretamente do stdout do cloudflared
- sem conta/token/configuração manual
- sem Firewall/Admin

Diferença proposital: o CHAPA ID não fixa a porta 8000. Ele procura uma porta
livre entre 8100 e 8200 para poder coexistir com BI Operacional e outros apps.


## V2.0 — Reconhecimento assistido pelo Catálogo Leo

Esta versão transforma o catálogo MDF do site da Leo em uma base visual de referência.

### Novo fluxo
1. Abra **Catálogo Leo** e execute **Sincronizar catálogo MDF**.
2. O CHAPA ID coleta de forma controlada SKU, descrição, fabricante, URL do produto e imagem principal.
3. Cada imagem é vinculada ao SKU no SQLite e recebe uma assinatura visual.
4. Na tela **Identificar**, fotografe a chapa física.
5. O sistema compara a foto com as imagens do catálogo e com fotos físicas já confirmadas.
6. São exibidas até 5 relações possíveis, com imagem, SKU, descrição e similaridade.
7. Ao confirmar o SKU correto, a foto física passa a ser uma nova referência daquele produto.

### Segurança operacional
- A identificação não confirma SKU automaticamente; o operador continua responsável pela confirmação.
- A sincronização roda em segundo plano, uma requisição por vez e com pausa entre acessos.
- Produtos já existentes preservam o endereço operacional importado.
- Imagens já sincronizadas não são baixadas novamente.
- O sistema registra última sincronização, produtos atualizados, imagens e erros.
- Se o site estiver indisponível, a base local já sincronizada continua funcionando.

### Observação
A estrutura do e-commerce pode mudar no futuro. O coletor foi isolado em `backend/app/services/leo_catalog.py` para permitir ajustes sem alterar o restante do CHAPA ID.

## V2.3 — Sincronização auditável + Cod. Interno
- Sincronização dividida em duas fases: leitura do catálogo e coleta dos produtos, cada uma com barra própria.
- Início, fim, duração, SKU atual, total localizado e eventos em tempo real.
- Logs detalhados no CMD durante toda a varredura e coleta.
- Números em pt-BR e percentual com uma casa decimal.
- Erros destacados e fila persistente para reprocessar somente os produtos que falharam.
- SKU oficial do Catálogo Leo = **Cod. Interno** da página; ID do produto/URL não é mais tratado como SKU.
- Correção automática de registros de versões anteriores vinculados pelo ID errado da URL.
- Identificação sinaliza empates visuais em vez de criar falsa certeza entre variações visualmente idênticas.
- Imagens dos candidatos podem ser ampliadas.
- Localização operacional usa o endereço da base importada quando o SKU correto existir; ausência é apresentada como pendência de cadastro, sem texto genérico.
