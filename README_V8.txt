CHAPA ID V8 — MOTOR VISUAL INDUSTRIAL PRO

Correções centrais desta versão:
- referências de catálogo classificadas antes do ranking: packshot, perfil, ambiente e imagens com fundo branco dominante não competem como textura da face da chapa;
- referências duplicadas no SQLite não inflam artificialmente o score do mesmo SKU;
- identidade perceptual de uploads do próprio catálogo tem prioridade sobre semelhança estética;
- comparação multi-crop/position-invariant continua ativa;
- imagens visualmente idênticas ligadas a SKUs diferentes formam grupo de equivalência visual: o padrão é identificado, mas o sistema não inventa espessura/faces;
- localização e impressão só são liberadas depois que o SKU exato estiver definido;
- IA continua como auditor apenas de candidatos fisicamente válidos e nunca deve escolher entre variações que a própria imagem não consegue distinguir;
- VALIDAR_V8.bat executa regressões específicas para o caso 5058240 x 5061911/12/13.

REGRA DE PRODUÇÃO:
Uma foto da face identifica padrão visual. Se diferentes espessuras/faces usam a mesma textura oficial, a decisão correta é pedir confirmação da variação, não fabricar certeza.
