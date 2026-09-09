CHAPA ID V4.1.4 - PAGINAÇÃO COMPROVADA + RECUPERAÇÃO DE LACUNAS

Correção do erro 3.696 / 3.984 no MDF:
- O contador de página NÃO avança mais apenas porque o clique foi executado.
- A página só é considerada lida quando realmente adiciona novos produtos.
- Se o site repetir os mesmos 24 cards, o sistema mantém a página atual e tenta novamente.
- Após tentativas normais, faz recuperação forte em página limpa e salta diretamente para a janela correta do paginador.
- Antes de cancelar uma leitura, executa uma auditoria final e revisita somente páginas com quantidade incompleta.
- Mantém proteção contra catálogo parcial; tolerância residual máxima de 0,5% apenas após recuperação automática.
- CMD mostra RECUPERAÇÃO PAGINAÇÃO quando o site não troca os cards corretamente.
- Preserva toda a base, imagens, Check-List incremental, scanner e proteção anti-SKU-stale.
