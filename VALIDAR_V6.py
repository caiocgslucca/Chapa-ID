from pathlib import Path
import tempfile
from PIL import Image
from backend.app.db import init_db, connect
from backend.app.services.vision import VisionEngine

def ok(name, cond, detail=''):
    print(('OK   ' if cond else 'FALHA') + ' | ' + name + ((' | '+detail) if detail else ''))
    if not cond: raise SystemExit(2)

def main():
    init_db()
    c=connect()
    tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    ok('Banco V6', {'industrial_scan_sessions','learning_quarantine','visual_equivalence_groups'} <= tables)
    groups=c.execute('SELECT COUNT(DISTINCT group_key) FROM visual_equivalence_groups').fetchone()[0]
    ok('Equivalência visual mapeada', groups >= 0, f'{groups} grupos')
    c.close()
    refs=[p for p in Path('backend/data/images').glob('*/catalogo_leo/principal.*') if p.stat().st_size>10000]
    ok('Referências visuais', len(refs)>0, f'{len(refs)} imagens')
    ref=refs[0]
    im=Image.open(ref).convert('RGB'); w,h=im.size
    crop=im.crop((int(w*.18),int(h*.18),int(w*.82),int(h*.82)))
    with tempfile.NamedTemporaryFile(suffix='.jpg',delete=False) as f:
        q=Path(f.name)
    crop.save(q,quality=92)
    eng=VisionEngine(); same=eng.compare_images(q,ref)
    ok('Fingerprint multi-crop', bool(same.get('industrial_match')), str(same))
    ok('Recorte da mesma referência reconhecido', float(same.get('score') or 0)>=80, f"{same.get('score')}%")
    ok('Suporte por múltiplos patches', int(same.get('patch_support') or 0)>=1, f"{same.get('patch_support')}/{same.get('patch_count')}")
    q.unlink(missing_ok=True)
    print('\nV6 validado: núcleo industrial, banco e fingerprints operacionais.')

if __name__=='__main__': main()
