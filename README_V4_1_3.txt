CHAPA ID V4.1.3 - CORREÇÃO FORTE DE SKU STALE

Correções desta versão:
- Coleta reduzida para 8 páginas paralelas por padrão para priorizar integridade.
- Cada produto inicia em about:blank antes da URL real, eliminando DOM residual da SPA.
- Se o Check-List detectar Cod. Interno incompatível com a descrição já cadastrada, ele NÃO grava erro imediatamente.
- O produto é reaberto em navegador/contexto novos e lido novamente em modo isolado.
- Só vira erro depois que o retry isolado também falhar.
- Anti-SKU-stale continua ativo: nunca grava Cod. Interno suspeito apenas para zerar o contador de erros.
- Imagens continuam com 8 fluxos paralelos.
- Base, imagens e histórico existentes são preservados.
