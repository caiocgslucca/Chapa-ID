from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'backend'))
from app.services.vision import engine
warm=ROOT/'backend/data/images/5061911/catalogo_leo/principal.jpg'
gray=ROOT/'backend/data/images/5059238/catalogo_leo/principal.jpg'
if not warm.exists() or not gray.exists():
    raise SystemExit('V9_FAIL: referencias de teste ausentes')
conflict=engine.compare_images(warm,gray)
identity=engine.compare_images(warm,warm)
print('warm x gray:',conflict)
print('warm x warm:',identity)
assert conflict.get('tone_gate') in {'color_family_mismatch','warm_neutral_conflict','neutral_chroma_conflict'}, conflict
assert float(conflict.get('score') or 0) <= 32.0, conflict
assert float(identity.get('score') or 0) >= 90.0, identity
print('V9_OK')
