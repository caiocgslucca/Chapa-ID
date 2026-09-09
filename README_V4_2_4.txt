CHAPA ID V4.2.4 - TRAVA FOTOMÉTRICA PROFISSIONAL

Correções principais:
- Não permite que gamma/correção de software transforme chapa branca escura em chapa cinza.
- Scanner detecta superfície neutra (branco/cinza/preto) em baixa luz e força torch/lanterna quando suportado.
- Tenta compensação de exposição do sensor antes de desistir.
- Se não houver iluminação física suficiente, bloqueia a identificação ao invés de fornecer SKU falso.
- Backend recebe métricas da imagem ORIGINAL, antes da correção, e revalida a decisão.
- Foto manual também carrega as métricas originais: ambiente escuro neutro não vira alta confiança artificial.
- Resultados só encerram scanner quando o backend libera safe_to_stop_scan.
