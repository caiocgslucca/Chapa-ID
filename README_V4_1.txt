CHAPA ID V4.1

Correções desta versão:
- ETA da Leitura do catálogo passa a usar total lido no DOM renderizado.
- Se o total oficial ainda não estiver disponível, a ETA usa ritmo real de páginas e muda automaticamente para o total oficial quando ele aparece.
- O contador de URLs únicas durante a leitura foi corrigido: os novos links agora são propagados ao agregador global.
- Check-List ganhou ledger persistente por item /p/<id> do site. O mesmo item não volta como novo em toda execução.
- Base antiga é migrada automaticamente a partir das source_url já conhecidas.
- Check-List só coleta item novo, erro pendente ou item cujo SKU não possui imagem física/indexação válida.
- Arquivos de imagem inexistentes (404 de /media) passam a ser considerados pendência real.
