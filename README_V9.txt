CHAPA ID V9 - MOTOR VISUAL INDUSTRIAL PRO - COR PRIMEIRO

Correcao principal:
- A familia de cor passa a ser uma trava fisica ANTES da textura.
- Marrom/amadeirado nao pode ser vencido por cinza/neutro apenas porque os veios sao parecidos.
- O motor usa percentis Lab e fracao de pixels quentes, nao apenas a media global.
- Isso reduz erro causado por reflexo, luz fria e sombras que deixam a media da foto artificialmente cinza.
- Candidato com familia cromatica incompatível e eliminado do ranking profissional.
- O resultado mostra "Cor detectada" para facilitar auditoria em campo.

Caso corrigido:
Uma chapa marrom estava retornando MDF Santorini cinza/texturizado. A V9 identifica evidência quente distribuida na foto e bloqueia referencias neutras antes de comparar textura.

Validacao:
Execute VALIDAR_V9.bat. O esperado e V9_OK.
