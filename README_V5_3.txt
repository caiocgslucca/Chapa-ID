CHAPA ID V5.3 — MOTOR MULTIMODAL AUDITÁVEL

Principais melhorias:
- IA participa de verdade do /identify quando a análise local fica ambígua.
- Recuperação fotométrica para branco/cinza/preto em ambiente escuro.
- Scanner não encerra simplesmente sem resultado: após tentativa de iluminação física,
  envia a melhor captura original para auditoria multimodal segura.
- Gemini/OpenAI recebem somente candidatos visuais plausíveis do motor local.
- IA pode rejeitar todos; não é obrigada a inventar SKU.
- Resultado de recuperação exige confiança de IA >= 88%.
- Decisão mostra origem: Local, IA auditada, Recuperação multimodal ou Rejeição.
- Logs profissionais no CMD:
  [CHAPA-ID][CAPTURE]
  [CHAPA-ID][LOCAL]
  [CHAPA-ID][IA] AUDIT/RECOVERY
  [CHAPA-ID][DECISION]
- Scanner final envia contexto fotométrico completo ao backend.
- Mantidas as travas físicas, aprendizado supervisionado, catálogo incremental,
  proteção da chave e teste resiliente ao Cloudflare.

Importante:
Nenhum sistema de visão deve prometer 100% de acerto em todas as condições.
Nesta versão, baixa evidência gera rejeição ou segunda opinião por IA, não um SKU inventado.
