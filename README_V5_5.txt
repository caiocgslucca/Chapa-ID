CHAPA ID V5.5 — RECUPERAÇÃO IA DE BAIXA LATÊNCIA

Correções desta versão:
- Corrige o caso em que o Gemini escolhia um SKU com 85% e o backend apagava o resultado por exigir 88%.
- Recuperação fotométrica agora aceita seleção IA >=82% apenas como "confirmação necessária"; não vira confirmação automática.
- Reduz auditoria de recuperação para os 3 candidatos fisicamente mais plausíveis.
- Reduz resolução/compressão enviada à IA para diminuir latência sem alterar o catálogo ou a imagem original.
- Timeout específico de recuperação limitado a 16s para não deixar /identify morrer no Quick Tunnel.
- Mantém trava anti-falso: abaixo do limite, o sistema continua sem exibir SKU.
- Logs continuam mostrando RECOVERY START / END / ERROR e a decisão final.
