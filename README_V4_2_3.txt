CHAPA ID V4.2.3 - SCANNER ADAPTATIVO COM CONCLUSAO GARANTIDA

Principais ajustes:
- Scanner não fica mais indefinidamente calibrando: limite aproximado de 12 segundos.
- Primeiros 2,2 s tentam correção real da câmera (exposição/torch quando suportado).
- Se o aparelho não oferece controles, aplica correção fotométrica limitada em software e segue a análise.
- Cada frame do scanner usa modo FAST no backend (shortlist menor), reduzindo o tempo de resposta.
- A melhor captura é mantida durante o scan; ao estabilizar ou atingir o limite de tempo, roda uma análise FULL final.
- A análise final é persistida normalmente no histórico e permite confirmação do SKU.
- Foto manual também recebe correção limitada de iluminação quando necessário.
- Timeout individual de frame evita o scanner ficar preso em uma requisição/túnel lenta.
- Backend calcula o descritor da foto uma única vez por análise e mantém cache dos descritores do catálogo.
- Scanner rápido: 32 candidatos x 1 referência; análise final: 100 candidatos x até 3 referências.
- As travas físicas de cor/tonalidade continuam ativas; correção de software permite ranking, mas não cria confiança falsa.
