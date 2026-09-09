CHAPA ID V4.1.5 - CORREÇÃO SKU STALE / RETRY ISOLADO

Correções principais:
- Cod. Interno agora só é aceito quando encontrado no mesmo bloco visual do H1 do produto atual.
- Removida a captura de códigos soltos de cards, recomendações ou DOM residual.
- Anti-colisão passou a validar QUALQUER SKU já existente, inclusive SKU criado na mesma execução.
- Um mesmo Cod. Interno não pode mais ser sobrescrito por descrições incompatíveis durante o Check-List.
- Mantida paginação V4.1.4 com recuperação de lacunas.

Sinal esperado no log:
- produtos corretos seguem OK/SKIP;
- se o site não expuser um Cod. Interno confiável no bloco do produto, o item vira erro/retry em vez de contaminar a base.
