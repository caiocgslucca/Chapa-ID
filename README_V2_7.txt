CHAPA ID V2.7 - PERFORMANCE TURBO SEGURA

Objetivo: reduzir fortemente o tempo da etapa 2 (Coleta dos dados) sem remover as validacoes que garantem Cod. Interno, descricao e imagem corretos.

Principais ajustes:
- 8 fluxos paralelos de coleta por padrao (adaptativo ao computador; maximo 10).
- 6 fluxos paralelos para download e indexacao das imagens (adaptativo; maximo 8).
- Removida navegacao about:blank antes de cada produto.
- Navegacao passa a esperar somente commit e valida o DOM em polling curto, preservando anti-SKU-stale.
- Bloqueio de imagens, fontes, midia e CSS durante a leitura do produto para reduzir trafego; a imagem oficial e baixada separadamente.
- Download e extracao do descritor visual deixam de bloquear a leitura do proximo SKU.
- Backpressure controlado para nao estourar memoria.
- ETA continua dinamico e passa a refletir a nova vazao real.
- A tela mostra separadamente os fluxos de coleta e de imagem.

Variaveis opcionais (nao precisa configurar):
CHAPA_ID_CATALOG_WORKERS=8
CHAPA_ID_IMAGE_WORKERS=6

O sistema continua validando que o Cod. Interno e o H1 pertencem ao produto solicitado antes de gravar.
