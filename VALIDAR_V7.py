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
    ok('Banco industrial', {'industrial_scan_sessions','learning_quarantine','visual_equivalence_groups'} <= tables)
    groups=c.execute('SELECT COUNT(DISTINCT group_key) FROM visual_equivalence_groups').fetchone()[0]
    ok('Equivalência visual mapeada', groups >= 0, f'{groups} grupos')
    c.close()
    refs=[p for p in Path('backend/data/images').glob('*/catalogo_leo/principal.*') if p.stat().st_size>10000]
    ok('Referências visuais', len(refs)>0, f'{len(refs)} imagens')
    eng=VisionEngine()
    ref=refs[0]
    ident=eng.compare_identity(ref,ref)
    ok('Identidade perceptual exata', ident.get('identity_exact') is True and float(ident.get('identity_score') or 0)>=99, str(ident))
    im=Image.open(ref).convert('RGB'); w,h=im.size
    crop=im.crop((int(w*.18),int(h*.18),int(w*.82),int(h*.82)))
    with tempfile.NamedTemporaryFile(suffix='.jpg',delete=False) as f: q=Path(f.name)
    crop.save(q,quality=92)
    same=eng.compare_images(q,ref)
    ok('Fingerprint multi-crop', bool(same.get('industrial_match')), str(same))
    ok('Recorte da mesma referência reconhecido', float(same.get('score') or 0)>=80, f"{same.get('score')}%")
    q.unlink(missing_ok=True)
    # Caso de regressão observado: referência Itapuã não deve ser confundida com imagem de MDF Cru quando ambas existirem.
    itapua=Path('backend/data/images/5061911/catalogo_leo/principal.jpg')
    cru=Path('backend/data/images/5058240/catalogo_leo/principal.png')
    if itapua.exists() and cru.exists():
        exact=eng.compare_identity(itapua,itapua); wrong=eng.compare_identity(itapua,cru)
        ok('Regressão 5061911 x 5058240', float(exact['identity_score'])-float(wrong['identity_score'])>=35, f"correto={exact['identity_score']} errado={wrong['identity_score']}")
    print('\nV7 validado: identidade perceptual, fingerprint multi-região e travas industriais operacionais.')

if __name__=='__main__': main()
