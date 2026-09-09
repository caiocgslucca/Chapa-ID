from pathlib import Path
import sqlite3, sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'backend'))
from app.main import _is_sheet_product
from app.services.vision import engine

assert _is_sheet_product('MDF Itapuã 18mm')
assert _is_sheet_product('Compensado Naval 18mm')
assert not _is_sheet_product('Rodapé Poliestireno Branco 480')
assert not _is_sheet_product('Sapata para Balaustre')

db=ROOT/'backend/data/chapa_id.sqlite3'
con=sqlite3.connect(db); con.row_factory=sqlite3.Row
# Não pode restar produto Leo com várias URLs de mídia simultâneas após a limpeza embutida no pacote.
bad=con.execute("""SELECT p.sku,COUNT(DISTINCT m.source_url) n FROM products p JOIN product_media m ON m.product_id=p.id WHERE m.source='leo_site' GROUP BY p.id HAVING n>1""").fetchall()
assert not bad, f'Mídia de catálogo contaminada ainda presente: {bad[:5]}'
# Caso real reportado: rodapé nunca pode ser elegível para identificação de chapa.
r=con.execute("SELECT description FROM products WHERE sku='5043210'").fetchone()
if r: assert not _is_sheet_product(r['description'])
con.close()
print('VALIDACAO V10: OK')
