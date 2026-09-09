CHAPA ID V10 — MOTOR VISUAL INDUSTRIAL
=====================================

Principais correções desta versão:

1. TRAVA DE DOMÍNIO
   O identificador aceita no ranking apenas chapas/painéis: MDF, MDP, compensado, OSB, painel, chapa, laminado, fórmica, HDF, hardboard e madeirite.
   Rodapé, porta, sapata, ripa, sarrafo, perfil e outros itens não podem mais vencer por semelhança de cor.

2. REFERÊNCIA VISUAL CURADA
   Fotos de ambiente, packshot com fundo branco, perfil/lateral e composições de produto ficam fora do ranking de textura.
   Elas continuam visíveis no catálogo, mas não são usadas para identificar a face da chapa.

3. CORREÇÃO DA CONTAMINAÇÃO DE CATÁLOGO
   Versões antigas podiam reutilizar o mesmo arquivo principal.jpg quando um Cod. Interno stale era lido pelo navegador.
   V10 audita o SQLite no startup e remove vínculos de mídia contaminados.
   O Check-List do Catálogo Leo rebaixa somente os SKUs que ficaram sem referência válida.

4. ANTI-SKU-STALE EM QUALQUER SINCRONIZAÇÃO
   A validação SKU x descrição x URL agora vale para sincronização completa e incremental.
   Conflito dispara retry isolado; se continuar incompatível, o item é rejeitado e vira erro pendente em vez de contaminar outro SKU.

5. ARQUIVO DE IMAGEM IMUTÁVEL POR URL
   Cada imagem oficial recebe nome derivado da própria URL. Uma coleta não sobrescreve mais a referência de outra página.

6. ABSTENÇÃO SEGURA
   Candidato sem referência de superfície válida ou fora da família de chapas é eliminado antes da decisão.
   Sem candidato confiável, o sistema responde 'Nenhuma correspondência segura'.

PASSO RECOMENDADO APÓS ABRIR V10
- Abra Catálogo Leo e execute Check-List.
- O sistema não repete SKUs íntegros; baixa/reindexa somente referências removidas pela auditoria V10, imagens faltantes, novos SKUs e erros pendentes.

A versão preserva login, Cloudflare, histórico, catálogo, configurações de IA e aprendizado supervisionado.
