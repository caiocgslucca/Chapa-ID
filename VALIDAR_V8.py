from pathlib import Path
from PIL import Image
import tempfile
from backend.app.services.vision import VisionEngine

ROOT=Path(__file__).resolve().parent
IMG=ROOT/'backend'/'data'/'images'
E=VisionEngine()

correct=IMG/'5061911'/'catalogo_leo'/'principal.jpg'
wrong=IMG/'5058240'/'catalogo_leo'/'principal.jpg'
var2=IMG/'5061912'/'catalogo_leo'/'principal.jpg'
var3=IMG/'5061913'/'catalogo_leo'/'principal.jpg'

assert correct.exists() and wrong.exists(), 'Imagens de regressão ausentes'

# 1) Packshot/perfil não pode ser usado como textura de face
p_wrong=E.reference_surface_profile(wrong)
p_correct=E.reference_surface_profile(correct)
assert not p_wrong['surface_usable'], p_wrong
assert p_correct['surface_usable'], p_correct

# 2) Própria imagem do catálogo precisa reconhecer identidade mesmo recomprimida
with tempfile.TemporaryDirectory() as td:
    q=Path(td)/'query.jpg'
    im=Image.open(correct).convert('RGB').resize((1080,720))
    im.save(q,quality=84,optimize=True)
    ident=E.compare_identity(q,correct)
    assert ident['identity_exact'], ident
    qd=E.verification_descriptor(q,query=True)
    ok=E.compare_query_descriptor_industrial(qd,correct)
    bad=E.compare_query_descriptor_industrial(qd,wrong)
    assert ok['score'] >= 98.0, ok
    # O errado pode até ter cor parecida, mas o perfil de superfície o elimina antes do ranking.
    assert not E.reference_surface_profile(wrong)['surface_usable']

# 3) Variações que usam a mesma textura oficial devem ser tratadas como equivalentes
for other in (var2,var3):
    eq=E.compare_identity(correct,other)
    assert eq['identity_exact'] or (eq['identity_near'] and eq['identity_score']>=94), eq

print('V8_OK')
print('5058240_surface=',p_wrong)
print('5061911_surface=',p_correct)
print('identity_recompressed=',ident)
print('correct_score=',ok['score'],'wrong_raw_score=',bad['score'])
