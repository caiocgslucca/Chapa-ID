CHAPA ID V7 — MOTOR VISUAL INDUSTRIAL PRO

Principais correções:
- Identidade perceptual para foto existente / própria imagem do catálogo (dHash + aHash + cor robusta).
- Upload de arquivo separado da câmera: imagem existente não sofre correção fotométrica artificial.
- Trava de fundo de referência: imagens de produto com fundo branco dominante não vencem fotos de superfície preenchida.
- Política de margem mínima: ranking apertado não vira SKU definitivo.
- Falha, timeout, HTTP 429/5xx da IA nunca aprova candidato fraco ou ambíguo.
- Abstenção explícita: candidato líder pode ser exibido sem afirmar SKU definido.
- Scanner só pode finalizar automaticamente quando há SKU definido e evidência suficiente.
- Motor industrial identificado como V7 no status/API.

REGRA CENTRAL: sem evidência suficiente, o sistema informa INCONCLUSIVO em vez de fabricar certeza.
