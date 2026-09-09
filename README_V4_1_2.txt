CHAPA ID V4.1.2 - CHECK-LIST + AUTO-REPARO DE IMAGENS

Correções:
- Corrigido FALHA: name 're' is not defined no Check-List incremental.
- Auto-reparo de caminhos absolutos antigos das imagens ao iniciar o sistema.
- Endpoint /media agora localiza a imagem pelo SKU mesmo quando o projeto foi movido de pasta/notebook.
- Ao encontrar a imagem, o SQLite é corrigido automaticamente para o caminho atual.
- Mantido Check-List incremental: SKUs já sincronizados não devem ser baixados novamente.
- Base e arquivos de imagem existentes são preservados.

Resultado esperado:
Ao abrir o Catálogo Leo, as imagens já existentes voltam a carregar sem exigir nova sincronização completa.
