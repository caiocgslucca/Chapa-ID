CHAPA ID V4.2.2 - SCANNER FOTOMETRICO ANTI-ERRO

Principais protecoes:
- Diagnostico de ambiente antes de identificar: pouca luz, subexposicao, estouro, reflexo e dominante de cor.
- Superficies lisas/neutras entram em modo de calibracao para evitar confundir branco, cinza e preto.
- Scanner tenta foco continuo, exposicao automatica, compensacao de exposicao e iluminacao auxiliar/torch quando o dispositivo permitir.
- Frames escuros ou com reflexo nao sao enviados para decisao final.
- Iluminacao controlada e validada antes de liberar superficie fotometricamente ambigua.
- O backend bloqueia qualquer resultado quando a captura ainda nao e segura.
- Continua exigindo 3 leituras consecutivas do mesmo SKU.
- Foto manual escura/reflexiva retorna 'Nenhuma correspondencia segura' em vez de chutar um SKU.

Regra: quando a camera nao consegue controlar o ambiente, o sistema prefere pedir nova captura a apresentar um SKU incorreto.
