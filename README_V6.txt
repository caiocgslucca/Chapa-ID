CHAPA ID V6 — MOTOR VISUAL INDUSTRIAL
=====================================

OBJETIVO
-------
Reduzir falsos positivos e tornar o reconhecimento robusto à região fotografada da chapa,
iluminação, repetição de padrões e SKUs visualmente equivalentes.

MUDANÇAS PRINCIPAIS DA V6
-------------------------
1. Fingerprint multi-crop/multi-região da imagem do catálogo.
   - A referência oficial não é tratada como uma única foto fixa.
   - O motor cria 13 regiões sobrepostas por referência em memória/cache.
   - A consulta pode casar com qualquer parte plausível do padrão.
   - O score final combina melhor região + mediana das melhores regiões + suporte de patches.

2. Scanner por consenso multi-região.
   - O operador percorre a chapa inteira.
   - O app mede cobertura, diversidade visual e estabilidade de cor.
   - Finalizar exige no mínimo 4 regiões distintas.
   - Até 4 keyframes diferentes passam por verificação completa.
   - Um SKU precisa aparecer consistentemente em múltiplas regiões.
   - Coincidência isolada é recusada.

3. Abstenção segura.
   - O V6 pode responder que não possui evidência suficiente.
   - Cor/iluminação incompatível não é compensada por textura.
   - IA não recebe candidatos eliminados pelas travas físicas.

4. Equivalência visual.
   - Variantes tecnicamente semelhantes são pré-mapeadas por descrição normalizada.
   - Espessura, faces e dimensão não são inventadas pela câmera quando visualmente indistinguíveis.
   - O agrupamento é candidato técnico e não confirmação automática.

5. Aprendizado com quarentena.
   - Confirmações/correções são registradas em learning_quarantine.
   - Correções não entram silenciosamente como referência positiva.
   - Apenas confirmação consistente >= 90% pode ser aprovada automaticamente.

6. Auditoria industrial.
   - Tabela industrial_scan_sessions registra cobertura/consenso das varreduras.
   - /industrial/status informa recursos ativos da V6.
   - Check Profissional inclui Motor V6, quarentena e equivalência visual.

7. Fotometria e IA preservadas.
   - Mantidas as travas de branco/cinza/preto, luz insuficiente, reflexo e dominante de cor.
   - Gemini/OpenAI continuam como auditores dos finalistas; não são autoridade para ignorar a física.

8. Quick Tunnel.
   - Launcher da V5.8 já aguarda DNS + Cloudflare + /health-public antes de abrir o navegador.
   - Mantido na V6 para evitar DNS_PROBE_FINISHED_NXDOMAIN na inicialização.

VALIDAÇÃO
---------
Execute VALIDAR_V6.bat para testar banco, tabelas industriais e fingerprint multi-crop.

TESTE OPERACIONAL RECOMENDADO
-----------------------------
- Percorrer centro, bordas e regiões com veios/desenhos diferentes.
- Aguardar cobertura e estabilidade de cor.
- Clicar Finalizar scanner.
- Em padrão visualmente equivalente, confirmar dados técnicos antes do SKU exato.
- Nunca usar alta porcentagem isolada como prova de SKU: observar consenso e margem.

IMPORTANTE
----------
A câmera comum não é colorímetro. O V6 reduz incerteza com estabilidade entre regiões,
travas físicas e consenso; quando a evidência não é suficiente, recusa a identificação.
