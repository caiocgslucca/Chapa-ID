CHAPA ID V2.8 - ALTA VAZAO SEGURA

Objetivo
- Reduzir fortemente o tempo total de sincronizacao sem alterar a regra oficial do Cod. Interno.

Mudancas principais
- Leitura MDF e Madeiras em paralelo: duas varreduras independentes ao mesmo tempo.
- Coleta padrao aumentada para 20 paginas paralelas.
- Coleta distribuida em 2 processos de navegador para evitar gargalo de rede de um unico Chromium.
- Limite tecnico de ate 24 paginas paralelas via CHAPA_ID_CATALOG_WORKERS.
- 8 fluxos de imagem por padrao, mantendo download/indexacao fora da navegacao principal.
- Timeout de coleta reduzido para 18 s por SKU; erros continuam isolados e podem ser reprocessados.
- Continua bloqueando imagens, fontes, CSS e midia durante a navegacao, preservando JS/XHR necessario para Cod. Interno e H1.
- Validacao anti-SKU-stale continua ativa.

Expectativa
- O ganho depende do site, CPU, memoria e internet.
- Com os logs observados da V2.7, o gargalo principal estava na navegacao de produto, nao nas imagens.
- A V2.8 ataca tambem a fase de leitura, que estava consumindo varios minutos antes da coleta.

Nao foi removido
- Cod. Interno como SKU oficial.
- Validacao de descricao/H1.
- Controle de erros.
- Processamento de imagens.
- Persistencia serial segura no banco.
