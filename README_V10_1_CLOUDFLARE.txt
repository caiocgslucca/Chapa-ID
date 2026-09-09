CHAPA ID V10.1 - HOTFIX CLOUDFLARE / REDE CORPORATIVA

Correção aplicada:
- Cloudflared agora inicia com --protocol http2 para não tentar QUIC/UDP 7844 primeiro.
- Evita o atraso e timeout 'Failed to dial a quic connection'.
- Se a rede bloquear TCP/7844, o launcher informa claramente que o backend está funcionando e que o bloqueio é externo à aplicação.
- O acesso local continua disponível em http://127.0.0.1:<porta>.

IMPORTANTE:
Cloudflare Tunnel precisa de saída TCP/7844 no modo HTTP/2. Se a rede corporativa bloquear essa porta, nenhum ajuste no código do CHAPA ID consegue criar o túnel por essa rede. Nesse caso use outra rede/hotspot ou solicite à TI liberação de saída TCP/7844 para cloudflared.exe.

Validação backend V10 executada: OK.
