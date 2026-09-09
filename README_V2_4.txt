CHAPA ID V2.4 - CORREÇÃO COLETA COD. INTERNO

Correção principal:
- O ID /p/10280816 NÃO é SKU.
- O SKU oficial é o campo visível "Cod. Interno" da página (ex.: 5061911).
- As páginas de produto da Leo renderizam esses dados via JavaScript; por isso a coleta agora usa uma sessão persistente do Edge/Chrome para ler o DOM já renderizado.
- Uma única sessão é reutilizada em toda a coleta, evitando abrir/fechar navegador para cada SKU.
- Logs no CMD exibem: índice, Cod. Interno, status da imagem e descrição.
- Reprocessamento de erros usa o mesmo método renderizado.

Exemplo validado pelo parser:
URL: /p/10280816/...
Cod. Interno: 5061911
Descrição: MDF Itapuã Essencial Wood 1 Face Branca Ultra Premium 6mm 2750x1850mm Duratex
Resultado esperado: SKU 5061911.
