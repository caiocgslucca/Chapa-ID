CHAPA ID V2.5 - SINCRONIZACAO RAPIDA + PREVISAO DINAMICA

Principais melhorias:
- Previsao dinamica de termino baseada na velocidade real da coleta.
- Exibe tempo restante, segundos/SKU, SKUs/min e quantidade de fluxos paralelos.
- Coleta em 4 paginas paralelas dentro de um unico navegador, mantendo gravacao do banco serial e segura.
- Bloqueio de imagens/fontes/midia durante a navegacao; a imagem oficial continua sendo baixada separadamente apos validar o produto.
- Protecao contra dado "stale": limpa a pagina entre produtos e valida que o H1 corresponde ao slug da URL antes de aceitar o Cod. Interno.
- SKU oficial continua sendo exclusivamente o valor de "Cod. Interno".
- O ETA se recalcula durante toda a execucao com peso maior para a velocidade recente.
- Erros continuam isolados e podem ser reprocessados sem refazer os produtos concluidos.

Observacao: o ganho real depende da velocidade do site da Leo e da internet. A configuracao de 4 fluxos foi escolhida para acelerar sem abrir dezenas de sessoes simultaneas.
