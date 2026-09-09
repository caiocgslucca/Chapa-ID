CHAPA ID V2.9 - ALTA VAZÃO ANTI-TRAVAMENTO

CORREÇÃO CRÍTICA DA V2.8
- Corrigido deadlock entre Leitura do Catálogo e Coleta dos Dados.
- Na V2.8 a fila asyncio tinha limite e era preenchida inteira antes dos workers iniciarem.
- Com milhares de URLs, a fila lotava e bloqueava para sempre em 0/5.325.

NOVO FLUXO
1. Abre os 2 navegadores.
2. Inicializa imediatamente os 20 coletores.
3. Um feeder assíncrono alimenta a fila gradualmente.
4. Backpressure continua ativo, sem estourar memória.
5. 8 fluxos de imagem continuam independentes.
6. Validação anti-SKU-stale preservada.
7. Banco continua serial e seguro.

A coleta deve começar a registrar OK 1/N poucos segundos após a leitura concluir.
