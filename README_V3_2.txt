CHAPA ID V3.2 - LEITURA ÍNTEGRA + ETA REAL

Correções principais:
- Total oficial de MDF e Madeiras é lido do DOM renderizado do próprio site.
- ETA da leitura usa trabalho real das duas categorias e começa assim que há amostra suficiente.
- Contador principal mostra URLs únicas globais, sem somar duplicados entre MDF e Madeiras.
- O total não deve mais cair ao terminar a leitura (ex.: 5,3 mil -> 4,8 mil).
- Paginação usa href quando disponível, retries, avanço de janela e recuperação por reload.
- Se a paginação parar antes do total oficial, a sincronização FALHA em vez de aceitar catálogo parcial.
- Validação de integridade exige todas as páginas oficiais e pelo menos 98% dos cards esperados.
- Coleta continua com 16 fluxos + 8 imagens e retry silencioso da V3.1.
