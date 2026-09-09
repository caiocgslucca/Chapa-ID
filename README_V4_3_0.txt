CHAPA ID V4.3.0 — SCANNER FOTOMÉTRICO ATIVO

Mudança de arquitetura:
1. Scanner mede luminosidade ANTES do torch.
2. Liga torch/lanterna quando disponível.
3. Mede novamente e exige ganho físico real de luz.
4. Só marca controlled_light quando o ganho foi comprovado.
5. Sob luz validada usa frame original, sem gamma artificial.
6. Branco/cinza/preto em pouca luz sem validação física = SEM RESULTADO, nunca SKU falso.
7. Foto manual naturalmente clara (inclusive flash) é aceita.
8. Backend revalida métricas originais e ignora software como prova de cor.
9. Comparador visual aplica trava específica branco × cinza × preto.
10. Scanner continua com timeout: falha de iluminação vira mensagem clara, não loop infinito.
