CHAPA ID V5.4 — IA AUTO-ATIVA / RECUPERAÇÃO FOTOMÉTRICA

Correção crítica baseada no log real do teste:
- O log mostrava recovery_candidates=5, guard=True e ai=disabled.
- A API estava configurada/testada, mas o checkbox "Auditoria por IA" estava desligado.
- Agora modo Híbrido ou IA + chave configurada ativa o auditor automaticamente.
- O checkbox redundante foi removido da interface para impedir configuração contraditória.
- "Somente Local" é a forma explícita de desligar IA.
- Em superfície neutra/ambiente difícil, os 5 candidatos plausíveis entram na recuperação multimodal.
- Logs mostram AUTO-ENABLE, RECOVERY START/END e DECISION.

Resultado esperado no mesmo teste:
[CHAPA-ID][IA] AUTO-ENABLE ... (apenas se banco ainda tiver enabled=0)
[CHAPA-ID][IA] RECOVERY START ...
[CHAPA-ID][IA] RECOVERY END ...
[CHAPA-ID][DECISION] source=ai_photometric_recovery ...

A IA continua sem poder escolher produto fora dos candidatos fisicamente plausíveis.
