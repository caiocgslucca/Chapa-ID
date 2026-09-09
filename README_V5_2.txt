CHAPA ID V5.2 — TESTE DE IA RESILIENTE AO CLOUDFLARE

- Teste de conexão não mantém mais uma requisição longa aberta pelo Quick Tunnel.
- POST /settings/ai/test/start retorna imediatamente e a chamada Gemini/OpenAI roda em thread no backend.
- Frontend consulta status em requisições curtas e retenta automaticamente em 502/503/504.
- Erros HTML do Cloudflare não são mais despejados na tela.
- Mensagens profissionais para chave inválida, modelo inexistente, quota, indisponibilidade e timeout.
- Chave nova é protegida no servidor antes do teste em background.
- Compatibilidade mantida com /settings/ai/test.
