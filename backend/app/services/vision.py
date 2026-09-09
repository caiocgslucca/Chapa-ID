from __future__ import annotations
from PIL import Image, ImageOps
import numpy as np
import json
from pathlib import Path

FEATURE_VERSION = 2

class VisionEngine:
    """Descritor visual local, determinístico e mais discriminativo para chapas.

    Continua leve (Pillow + NumPy), mas combina cor, textura, gradientes e
    distribuição espacial. Isso reduz empates artificiais do descritor antigo,
    que usava apenas histogramas RGB globais + 6 medidas de textura.
    """

    def __init__(self):
        # Cache apenas das referências do catálogo. Elas são reutilizadas em milhares
        # de leituras do scanner e não precisam ser recalculadas a cada frame.
        self._reference_descriptor_cache: dict[tuple[str, int], dict] = {}
        self._reference_cache_order: list[tuple[str, int]] = []
        self._reference_cache_limit = 1200
        self._industrial_patch_cache: dict[tuple[str, int], list[dict]] = {}
        self._industrial_patch_order: list[tuple[str, int]] = []
        self._industrial_patch_cache_limit = 700
        self._identity_cache: dict[tuple[str, int], dict] = {}
        self._identity_cache_order: list[tuple[str, int]] = []
        self._identity_cache_limit = 1800

    def _norm(self, v: np.ndarray) -> np.ndarray:
        v = np.asarray(v, dtype=np.float32)
        n = float(np.linalg.norm(v))
        return v / n if n > 1e-12 else v

    def extract(self, image_path: str | Path) -> list[float]:
        img = Image.open(image_path).convert("RGB")
        img = ImageOps.exif_transpose(img)
        img = ImageOps.fit(img, (192, 192), method=Image.Resampling.LANCZOS)
        arr = np.asarray(img).astype(np.float32) / 255.0
        gray = arr.mean(axis=2)
        feats: list[float] = []

        # 1) Cor global: histogramas mais finos RGB + luminância.
        for c in range(3):
            hist, _ = np.histogram(arr[:, :, c], bins=24, range=(0, 1), density=False)
            hist = hist.astype(np.float32) / max(float(hist.sum()), 1.0)
            feats.extend(hist.tolist())
        hgray, _ = np.histogram(gray, bins=24, range=(0, 1), density=False)
        hgray = hgray.astype(np.float32) / max(float(hgray.sum()), 1.0)
        feats.extend(hgray.tolist())

        # 2) Gradientes/orientação: diferencia veios horizontais, verticais e diagonais.
        gx = np.zeros_like(gray); gy = np.zeros_like(gray)
        gx[:, 1:-1] = (gray[:, 2:] - gray[:, :-2]) * 0.5
        gy[1:-1, :] = (gray[2:, :] - gray[:-2, :]) * 0.5
        mag = np.sqrt(gx * gx + gy * gy)
        ang = (np.arctan2(gy, gx) + np.pi) % np.pi
        bins = np.linspace(0, np.pi, 13)
        orient = np.zeros(12, dtype=np.float32)
        for i in range(12):
            mask = (ang >= bins[i]) & (ang < bins[i + 1])
            orient[i] = float(mag[mask].sum())
        orient = orient / max(float(orient.sum()), 1e-8)
        feats.extend(orient.tolist())

        # 3) Textura local por diferenças em múltiplas distâncias.
        for step in (1, 2, 4, 8):
            dx = np.abs(gray[:, step:] - gray[:, :-step])
            dy = np.abs(gray[step:, :] - gray[:-step, :])
            feats.extend([
                float(dx.mean()), float(dx.std()), float(np.percentile(dx, 75)),
                float(dy.mean()), float(dy.std()), float(np.percentile(dy, 75)),
            ])

        # 4) Assinatura espacial 4x4: média/desvio por bloco em RGB + cinza.
        for iy in range(4):
            for ix in range(4):
                y0, y1 = iy * 48, (iy + 1) * 48
                x0, x1 = ix * 48, (ix + 1) * 48
                block = arr[y0:y1, x0:x1]
                g = gray[y0:y1, x0:x1]
                feats.extend(block.mean(axis=(0, 1)).tolist())
                feats.extend(block.std(axis=(0, 1)).tolist())
                feats.extend([float(g.mean()), float(g.std())])

        # 5) Perfil de veios: energia média por faixas horizontais/verticais.
        row_profile = gray.mean(axis=1)
        col_profile = gray.mean(axis=0)
        for profile in (row_profile, col_profile):
            # 24 amostras suavizadas do perfil, invariantes a pequenas diferenças de escala.
            chunks = np.array_split(profile, 24)
            vals = np.asarray([float(c.mean()) for c in chunks], dtype=np.float32)
            vals = vals - vals.mean()
            sd = float(vals.std())
            if sd > 1e-8: vals = vals / sd
            feats.extend(vals.tolist())

        return self._norm(np.asarray(feats, dtype=np.float32)).tolist()


    def _rgb_to_lab(self, arr: np.ndarray) -> np.ndarray:
        """Converte RGB 0..1 para CIE Lab (D65), sem dependência externa."""
        rgb = np.clip(arr.astype(np.float32), 0.0, 1.0)
        lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        x = lin[...,0]*0.4124564 + lin[...,1]*0.3575761 + lin[...,2]*0.1804375
        y = lin[...,0]*0.2126729 + lin[...,1]*0.7151522 + lin[...,2]*0.0721750
        z = lin[...,0]*0.0193339 + lin[...,1]*0.1191920 + lin[...,2]*0.9503041
        x = x / 0.95047; z = z / 1.08883
        e = 216.0/24389.0; k = 24389.0/27.0
        def f(t):
            return np.where(t > e, np.cbrt(t), (k*t + 16.0)/116.0)
        fx, fy, fz = f(x), f(y), f(z)
        return np.stack([116*fy-16, 500*(fx-fy), 200*(fy-fz)], axis=-1)

    def _bhattacharyya(self, a: np.ndarray, b: np.ndarray) -> float:
        a=np.asarray(a,dtype=np.float32); b=np.asarray(b,dtype=np.float32)
        a=a/max(float(a.sum()),1e-12); b=b/max(float(b.sum()),1e-12)
        return float(np.sqrt(a*b).sum())

    def _border_object_crop(self, img: Image.Image) -> Image.Image:
        """Remove fundo de estúdio do catálogo quando ele domina as bordas.

        Muitas imagens oficiais têm a chapa escura sobre um fundo branco. Comparar a
        imagem inteira faz o fundo branco dominar o histograma e pode aproximar uma
        chapa preta de uma foto branca. Aqui isolamos o produto pelo contraste com a
        cor das bordas. Se a segmentação não for confiável, usamos um crop central.
        """
        arr=np.asarray(img.convert('RGB')).astype(np.float32)/255.0
        h,w=arr.shape[:2]
        if h<32 or w<32:
            return img
        bw=max(3,int(min(h,w)*0.055))
        border=np.concatenate([
            arr[:bw,:,:].reshape(-1,3),arr[-bw:,:,:].reshape(-1,3),
            arr[:, :bw,:].reshape(-1,3),arr[:, -bw:,:].reshape(-1,3)
        ],axis=0)
        bg=np.median(border,axis=0)
        # distância RGB ao fundo + diferença de luminância
        dist=np.linalg.norm(arr-bg[None,None,:],axis=2)
        lum=arr.mean(axis=2); bg_l=float(bg.mean())
        mask=(dist>0.105) | (np.abs(lum-bg_l)>0.095)
        ys,xs=np.where(mask)
        coverage=float(mask.mean())
        if len(xs)>80 and 0.08<=coverage<=0.86:
            x0,x1=int(xs.min()),int(xs.max())+1; y0,y1=int(ys.min()),int(ys.max())+1
            pad=max(2,int(min(h,w)*0.015))
            x0=max(0,x0-pad); y0=max(0,y0-pad); x1=min(w,x1+pad); y1=min(h,y1+pad)
            if (x1-x0)>w*0.25 and (y1-y0)>h*0.18:
                return img.crop((x0,y0,x1,y1))
        # fallback: região central reduz bordas/fundo sem assumir geometria específica
        mx=int(w*0.10); my=int(h*0.10)
        return img.crop((mx,my,w-mx,h-my))

    def _prepare_verification_image(self, image_path: str | Path, query: bool=False) -> Image.Image:
        img=Image.open(image_path).convert('RGB')
        img=ImageOps.exif_transpose(img)
        if query:
            # A foto física deve preencher o quadro. Cortamos as bordas para reduzir
            # mão, chão, reflexos periféricos e ambiente ao redor da chapa.
            w,h=img.size
            mx=int(w*0.12); my=int(h*0.12)
            if w>80 and h>80:
                img=img.crop((mx,my,w-mx,h-my))
        else:
            img=self._border_object_crop(img)
        return ImageOps.fit(img,(224,224),method=Image.Resampling.LANCZOS)

    def _descriptor_from_image(self, img: Image.Image) -> dict:
        """Calcula o descritor sobre uma imagem já preparada."""
        arr=np.asarray(img.convert("RGB")).astype(np.float32)/255.0
        lab=self._rgb_to_lab(arr); gray=arr.mean(axis=2)
        gx=np.zeros_like(gray); gy=np.zeros_like(gray)
        gx[:,1:-1]=(gray[:,2:]-gray[:,:-2])*0.5
        gy[1:-1,:]=(gray[2:,:]-gray[:-2,:])*0.5
        mag=np.sqrt(gx*gx+gy*gy)
        ang=(np.arctan2(gy,gx)+np.pi)%np.pi
        orient=np.zeros(18,dtype=np.float32); edges=np.linspace(0,np.pi,19)
        for i in range(18):
            mask=(ang>=edges[i])&(ang<edges[i+1]); orient[i]=float(mag[mask].sum())

        g=(gray*255).astype(np.uint8); c=g[1:-1,1:-1]
        nbr=[g[:-2,:-2],g[:-2,1:-1],g[:-2,2:],g[1:-1,2:],g[2:,2:],g[2:,1:-1],g[2:,:-2],g[1:-1,:-2]]
        code=np.zeros_like(c,dtype=np.uint8)
        for i,n in enumerate(nbr): code |= ((n>=c).astype(np.uint8)<<i)

        tex=[]
        for step in (1,2,4,8,16):
            dx=np.abs(gray[:,step:]-gray[:,:-step]); dy=np.abs(gray[step:,:]-gray[:-step,:])
            tex += [float(dx.mean()),float(dx.std()),float(np.percentile(dx,75)),float(dy.mean()),float(dy.std()),float(np.percentile(dy,75))]

        L=lab[...,0]; A=lab[...,1]; B=lab[...,2]
        chroma=np.sqrt(A*A+B*B)
        sat=arr.max(axis=2)-arr.min(axis=2)
        # V9 — assinatura cromática robusta. A mediana global pode parecer neutra
        # quando há reflexo/frio de iluminação, mesmo em uma madeira marrom. Por isso
        # registramos também percentis e a fração de pixels quentes. Esse sinal entra
        # antes da textura no ranking e impede cinza de vencer marrom por veios parecidos.
        b50=float(np.percentile(B,50)); b65=float(np.percentile(B,65)); b75=float(np.percentile(B,75)); b90=float(np.percentile(B,90))
        a50=float(np.percentile(A,50)); a75=float(np.percentile(A,75))
        warm_frac5=float(np.mean(B>5.0)); warm_frac8=float(np.mean(B>8.0))
        cool_frac=float(np.mean(B<-4.0)); chroma75=float(np.percentile(chroma,75))
        return {
            'mean_lab':np.mean(lab,axis=(0,1)),
            'median_lab':np.median(lab.reshape(-1,3),axis=0),
            'lab_hist':[np.histogram(L,24,(0,100))[0],np.histogram(A,24,(-80,80))[0],np.histogram(B,24,(-80,80))[0]],
            'orient':orient,
            'mag_hist':np.histogram(mag,24,(0,0.35))[0],
            'lbp':np.histogram(code,32,(0,256))[0],
            'tex':np.asarray(tex,dtype=np.float32),
            'l10':float(np.percentile(L,10)), 'l50':float(np.percentile(L,50)), 'l90':float(np.percentile(L,90)),
            'white_frac':float(np.mean((L>78)&(chroma<18))),
            'dark_frac':float(np.mean(L<32)),
            'neutral_frac':float(np.mean(chroma<12)),
            'b50':b50,'b65':b65,'b75':b75,'b90':b90,'a50':a50,'a75':a75,
            'warm_frac5':warm_frac5,'warm_frac8':warm_frac8,'cool_frac':cool_frac,'chroma75':chroma75,
            'sat50':float(np.percentile(sat,50)),
            'contrast':float(np.std(L)),
            'edge':float(np.mean(mag)),
        }

    def _verification_descriptor(self, image_path: str | Path, query: bool=False) -> dict:
        """Descritor de verificação de alta precisão com isolamento do produto."""
        img=self._prepare_verification_image(image_path,query=query)
        return self._descriptor_from_image(img)

    def _capture_environment(self, image_path: str | Path) -> dict:
        """Diagnóstico fotométrico para impedir decisões em captura ruim.

        Uma superfície branca em ambiente escuro e uma superfície realmente cinza/escura
        podem ser fisicamente ambíguas em uma única foto. Em vez de inventar um SKU,
        classificamos o risco e exigimos uma captura com exposição controlada.
        """
        img=self._prepare_verification_image(image_path,query=True)
        arr=np.asarray(img).astype(np.float32)/255.0
        gray=(0.2126*arr[:,:,0]+0.7152*arr[:,:,1]+0.0722*arr[:,:,2])
        p05,p10,p50,p90,p95=[float(np.percentile(gray,q)) for q in (5,10,50,90,95)]
        mean=float(gray.mean()); std=float(gray.std())
        dark=float(np.mean(gray<0.22)); clipped_dark=float(np.mean(gray<0.06)); clipped_light=float(np.mean(gray>0.97))
        # estimativa simples de dominante/cast; útil para avisar iluminação colorida
        rgb_mean=arr.mean(axis=(0,1)); cast=float((rgb_mean.max()-rgb_mean.min())/max(float(rgb_mean.mean()),1e-6))
        low_light=(p50<0.38 and p90<0.68) or dark>0.58
        very_dark=(p50<0.25 and p90<0.52) or dark>0.78
        overexposed=(p50>0.93 and clipped_light>0.24)
        glare=(clipped_light>0.10 and std>0.12)
        low_dynamic=(p90-p10)<0.12
        color_cast=cast>0.28
        return {
            'mean':mean,'p05':p05,'p10':p10,'p50':p50,'p90':p90,'p95':p95,'std':std,
            'dark_frac':dark,'clipped_dark':clipped_dark,'clipped_light':clipped_light,
            'cast':cast,'low_light':low_light,'very_dark':very_dark,'overexposed':overexposed,
            'glare':glare,'low_dynamic':low_dynamic,'color_cast':color_cast
        }

    def verification_descriptor(self, image_path: str | Path, query: bool=False) -> dict:
        return self._verification_descriptor(image_path, query=query)

    def _reference_descriptor_cached(self, image_path: str | Path) -> dict:
        p=Path(image_path)
        try:
            stamp=int(p.stat().st_mtime_ns)
        except Exception:
            stamp=0
        key=(str(p.resolve()),stamp)
        hit=self._reference_descriptor_cache.get(key)
        if hit is not None:
            return hit
        desc=self._verification_descriptor(p,query=False)
        self._reference_descriptor_cache[key]=desc
        self._reference_cache_order.append(key)
        if len(self._reference_cache_order)>self._reference_cache_limit:
            old=self._reference_cache_order.pop(0);self._reference_descriptor_cache.pop(old,None)
        return desc

    def _industrial_reference_patches(self, image_path: str | Path) -> list[dict]:
        """Cria fingerprints multi-região da referência oficial.

        A imagem do catálogo pode representar apenas uma região do padrão. Em vez de
        assumir que a foto física corresponde à mesma posição, dividimos a referência
        em crops sobrepostos e multi-escala e comparamos a consulta contra o conjunto.
        """
        p=Path(image_path)
        try: stamp=int(p.stat().st_mtime_ns)
        except Exception: stamp=0
        key=(str(p.resolve()),stamp)
        hit=self._industrial_patch_cache.get(key)
        if hit is not None: return hit
        base=self._prepare_verification_image(p,query=False)
        w,h=base.size
        boxes=[]
        # imagem inteira + centro em 80%
        boxes.append((0,0,w,h))
        boxes.append((int(w*.10),int(h*.10),int(w*.90),int(h*.90)))
        # 3x3 sobreposto: cada janela cobre ~62% da dimensão, preservando padrões grandes.
        cw,ch=int(w*.62),int(h*.62)
        xs=[0,(w-cw)//2,w-cw]; ys=[0,(h-ch)//2,h-ch]
        for y in ys:
            for x in xs: boxes.append((x,y,x+cw,y+ch))
        # faixas horizontais/verticais úteis para veios longos
        boxes += [(0,int(h*.18),w,int(h*.82)),(int(w*.18),0,int(w*.82),h)]
        out=[]
        seen=set()
        for box in boxes:
            if box in seen: continue
            seen.add(box)
            crop=base.crop(box)
            crop=ImageOps.fit(crop,(224,224),method=Image.Resampling.LANCZOS)
            out.append(self._descriptor_from_image(crop))
        self._industrial_patch_cache[key]=out
        self._industrial_patch_order.append(key)
        if len(self._industrial_patch_order)>self._industrial_patch_cache_limit:
            old=self._industrial_patch_order.pop(0); self._industrial_patch_cache.pop(old,None)
        return out

    def _identity_signature(self, image_path: str | Path) -> dict:
        """Assinatura perceptual V7 para reconhecer a própria imagem do catálogo.

        Não substitui o motor visual. É uma via de alta precisão para uploads que já
        existem na base (mesma referência com resize/recompressão). Combina dHash,
        aHash e estatísticas de cor para evitar falsos positivos.
        """
        p=Path(image_path)
        try: stamp=int(p.stat().st_mtime_ns)
        except Exception: stamp=0
        key=(str(p.resolve()),stamp)
        hit=self._identity_cache.get(key)
        if hit is not None: return hit
        img=ImageOps.exif_transpose(Image.open(p).convert("RGB"))
        # remove apenas borda quase branca uniforme; não recorta conteúdo real.
        arr0=np.asarray(ImageOps.contain(img,(256,256),method=Image.Resampling.LANCZOS),dtype=np.float32)/255.0
        gray_img=ImageOps.grayscale(img)
        dh=np.asarray(gray_img.resize((9,8),Image.Resampling.LANCZOS),dtype=np.float32)
        dbits=(dh[:,1:]>dh[:,:-1]).reshape(-1)
        ah=np.asarray(gray_img.resize((8,8),Image.Resampling.LANCZOS),dtype=np.float32)
        abits=(ah>float(ah.mean())).reshape(-1)
        # cor robusta: medianas e quartis reduzem impacto de compressão.
        flat=arr0.reshape(-1,3)
        color=np.concatenate([np.median(flat,axis=0),np.quantile(flat,.25,axis=0),np.quantile(flat,.75,axis=0)]).astype(np.float32)
        out={"dhash":dbits,"ahash":abits,"color":color}
        self._identity_cache[key]=out; self._identity_cache_order.append(key)
        if len(self._identity_cache_order)>self._identity_cache_limit:
            old=self._identity_cache_order.pop(0); self._identity_cache.pop(old,None)
        return out

    def compare_identity(self, query_path: str | Path, reference_path: str | Path) -> dict:
        """Retorna evidência de identidade da referência, não apenas semelhança estética."""
        try:
            q=self._identity_signature(query_path); r=self._identity_signature(reference_path)
            d=100.0*(1.0-float(np.mean(q["dhash"]!=r["dhash"])))
            a=100.0*(1.0-float(np.mean(q["ahash"]!=r["ahash"])))
            cd=float(np.linalg.norm(q["color"]-r["color"]))
            c=100.0*float(np.exp(-((cd/0.22)**2)))
            score=.50*d+.30*a+.20*c
            # identidade forte exige concordância dos hashes; cor sozinha nunca decide.
            exact=bool(d>=96.0 and a>=92.0 and c>=78.0)
            near=bool(d>=91.0 and a>=88.0 and c>=68.0)
            return {"identity_score":round(score,2),"identity_exact":exact,"identity_near":near,"dhash":round(d,1),"ahash":round(a,1),"identity_color":round(c,1)}
        except Exception:
            return {"identity_score":0.0,"identity_exact":False,"identity_near":False}

    def reference_surface_profile(self, image_path: str | Path) -> dict:
        """V10: classifica referência oficial como superfície, packshot ou ambiente.

        Só imagens que realmente representam a face da chapa podem participar do ranking.
        Fotos de ambiente, perfil, produto pequeno sobre fundo branco ou composição de
        e-commerce ficam disponíveis apenas para exibição.
        """
        try:
            img=ImageOps.exif_transpose(Image.open(image_path).convert("RGB"))
            img=ImageOps.contain(img,(360,360),method=Image.Resampling.LANCZOS)
            arr=np.asarray(img,dtype=np.float32)/255.0
            if arr.size==0: raise ValueError("imagem vazia")
            h,w=arr.shape[:2]
            gray=0.2126*arr[:,:,0]+0.7152*arr[:,:,1]+0.0722*arr[:,:,2]
            near_white=np.all(arr>=0.89,axis=2); white=np.all(arr>=0.94,axis=2)
            near_white_frac=float(near_white.mean()); white_frac=float(white.mean())
            bw=max(2,int(min(h,w)*0.08))
            border=np.concatenate([near_white[:bw,:].ravel(),near_white[-bw:,:].ravel(),near_white[:,:bw].ravel(),near_white[:,-bw:].ravel()])
            border_white=float(border.mean()) if border.size else 0.0
            content=~near_white; ys,xs=np.where(content)
            if len(xs)>20:
                span_x=(xs.max()-xs.min()+1)/max(w,1); span_y=(ys.max()-ys.min()+1)/max(h,1); bbox_fill=float(span_x*span_y)
            else: bbox_fill=0.0
            content_frac=1.0-near_white_frac

            # Estrutura espacial: superfícies de chapa tendem a preencher o quadro e
            # manter estatísticas parecidas entre blocos; fotos de ambiente têm regiões
            # muito diferentes (parede, piso, rodapé, objetos, sombras fortes).
            block_means=[]; block_stds=[]
            for iy in range(4):
                for ix in range(4):
                    y0,y1=iy*h//4,(iy+1)*h//4; x0,x1=ix*w//4,(ix+1)*w//4
                    b=gray[y0:y1,x0:x1]
                    block_means.append(float(b.mean())); block_stds.append(float(b.std()))
            block_mean_spread=float(np.std(block_means))
            block_texture_spread=float(np.std(block_stds))
            gx=np.zeros_like(gray); gy=np.zeros_like(gray)
            gx[:,1:-1]=(gray[:,2:]-gray[:,:-2])*0.5; gy[1:-1,:]=(gray[2:,:]-gray[:-2,:])*0.5
            mag=np.sqrt(gx*gx+gy*gy)
            edge_density=float(np.mean(mag>0.08))
            strong_edge_density=float(np.mean(mag>0.16))

            packshot=bool(near_white_frac>0.18 or border_white>0.32 or bbox_fill<0.82)
            scene_like=bool(block_mean_spread>0.145 or block_texture_spread>0.075 or strong_edge_density>0.075)
            # Textura muito lisa/clara ainda pode ser chapa: por isso edge baixo não reprova.
            surface=bool((not packshot) and (not scene_like) and content_frac>=0.76 and bbox_fill>=0.90)
            kind='surface' if surface else ('packshot' if packshot else 'scene_or_object')
            quality=100.0*max(0.0,min(1.0,
                content_frac*0.30 + bbox_fill*0.25 + (1-border_white)*0.15 +
                max(0.0,1-block_mean_spread/0.18)*0.20 + max(0.0,1-strong_edge_density/0.09)*0.10
            ))
            return {
                "surface_usable":surface,"surface_quality":round(quality,1),"reference_kind":kind,
                "white_background":round(white_frac,4),"near_white_background":round(near_white_frac,4),
                "border_white":round(border_white,4),"content_fraction":round(content_frac,4),"bbox_fill":round(bbox_fill,4),
                "block_mean_spread":round(block_mean_spread,4),"block_texture_spread":round(block_texture_spread,4),
                "edge_density":round(edge_density,4),"strong_edge_density":round(strong_edge_density,4)
            }
        except Exception as e:
            return {"surface_usable":False,"surface_quality":0.0,"reference_kind":"invalid","reference_profile_error":str(e)[:160]}

    def compare_query_descriptor_industrial(self, query_desc: dict, reference_path: str | Path) -> dict:
        """Comparação V7: robusta à posição do recorte no desenho da chapa."""
        try:
            patches=self._industrial_reference_patches(reference_path)
            comps=[self._compare_descriptors(query_desc,r) for r in patches]
            comps.sort(key=lambda x: float(x.get('score') or 0), reverse=True)
            if not comps: raise RuntimeError('sem patches')
            best=comps[0].copy()
            top=comps[:min(3,len(comps))]
            # O melhor patch prova correspondência local; os seguintes medem suporte
            # do mesmo padrão em outras regiões e evitam coincidência isolada.
            robust=float(np.median([float(x.get('score') or 0) for x in top]))
            best_score=float(best.get('score') or 0)
            support=sum(1 for x in comps if float(x.get('score') or 0)>=max(58.0,best_score-10.0))
            industrial=0.72*best_score+0.28*robust
            # Coincidência única recebe pequena penalização; padrão repetido ganha estabilidade.
            if support<=1 and best_score<92: industrial*=0.92
            elif support>=3: industrial=min(100.0,industrial+1.5)
            best['single_patch_score']=round(best_score,2)
            best['robust_patch_score']=round(robust,2)
            best['patch_support']=int(support)
            best['patch_count']=len(comps)
            best['score']=round(float(industrial),2)
            best['industrial_match']=True
            return best
        except Exception:
            try:
                r=self._reference_descriptor_cached(reference_path)
                return self._compare_descriptors(query_desc,r)
            except Exception:
                return {'score':0.0,'color':0.0,'texture':0.0,'delta_e':999.0,'tone_gate':'invalid'}

    def compare_query_descriptor(self, query_desc: dict, reference_path: str | Path) -> dict:
        return self.compare_query_descriptor_industrial(query_desc,reference_path)

    def assess_capture(self, image_path: str | Path) -> dict:
        """Avalia qualidade e ambiente antes de permitir uma decisão automática."""
        try:
            q=self._verification_descriptor(image_path,query=True)
            env=self._capture_environment(image_path)
        except Exception:
            return {'quality':0.0,'status':'invalid','message':'Imagem inválida.','safe_for_identification':False}

        l50=q['l50']; edge=q['edge']
        exposure=1.0
        if env['very_dark']:
            exposure=0.10
        elif env['low_light']:
            exposure=0.42
        elif env['overexposed']:
            exposure=0.32
        detail=min(1.0,max(0.0,(edge-0.0025)/0.018))
        detail=0.45+0.55*detail
        glare_factor=0.35 if env['glare'] else 1.0
        cast_factor=0.72 if env['color_cast'] else 1.0
        quality=100.0*(0.55*exposure+0.30*detail+0.15*glare_factor)*cast_factor

        # Superfície lisa + neutra sob luz ambiente é um caso fisicamente ambíguo:
        # branco em pouca luz pode virar cinza na câmera. Sem iluminação controlada
        # é melhor bloquear do que transformar esse cinza em um SKU errado.
        neutral_surface=bool(q['neutral_frac']>0.68 and q['edge']<0.0065 and q['contrast']<13.0)
        photometric_ambiguous=bool(neutral_surface and 30<=q['l50']<=86)

        risks=[]
        if env['very_dark']: risks.append('very_dark')
        elif env['low_light']: risks.append('low_light')
        if env['overexposed']: risks.append('overexposed')
        if env['glare']: risks.append('glare')
        if env['color_cast']: risks.append('color_cast')
        if photometric_ambiguous: risks.append('photometric_ambiguous')

        safe=not (env['very_dark'] or env['low_light'] or env['overexposed'] or env['glare'] or photometric_ambiguous)
        if env['very_dark']:
            status='blocked'; msg='Ambiente muito escuro. O scanner precisa corrigir a exposição ou acender a luz antes de identificar.'
        elif env['low_light']:
            status='blocked'; msg='Ambiente escuro detectado. A identificação foi bloqueada até a exposição ficar segura.'
        elif env['overexposed'] or env['glare']:
            status='blocked'; msg='Reflexo ou estouro de luz detectado. Mude o ângulo ou reduza a iluminação.'
        elif photometric_ambiguous:
            status='blocked'; msg='Superfície lisa/neutra com iluminação incerta. O scanner precisa calibrar a luz antes de definir a cor real.'
        elif env['color_cast']:
            status='medium'; msg='Iluminação com dominante de cor detectada; o sistema vai exigir maior estabilidade.'
        elif quality>=78:
            status='good'; msg='Captura adequada para identificação.'
        elif quality>=62:
            status='medium'; msg='Captura utilizável; mantenha a chapa centralizada e estável.'
        else:
            status='low'; msg='Melhore foco, distância e iluminação antes de identificar.'

        return {
            'quality':round(float(quality),1),'status':status,'message':msg,'safe_for_identification':bool(safe),
            'risks':risks,'low_light':bool(env['low_light']),'very_dark':bool(env['very_dark']),
            'overexposed':bool(env['overexposed']),'glare':bool(env['glare']),'color_cast':bool(env['color_cast']),
            'photometric_ambiguous':photometric_ambiguous,'neutral_surface':neutral_surface,'neutral_fraction':round(q['neutral_frac']*100,1),
            'brightness':round(env['mean']*100,1),'p50_brightness':round(env['p50']*100,1),
            'p90_brightness':round(env['p90']*100,1),'dark_fraction':round(env['dark_frac']*100,1),
            'l50':round(l50,1),'edge':round(edge,4)
        }

    def _compare_descriptors(self, q: dict, r: dict) -> dict:
        delta=float(np.linalg.norm(q['median_lab']-r['median_lab']))
        delta_mean=float(np.linalg.norm(q['mean_lab']-r['mean_lab']))
        mean_sim=float(np.exp(-((delta/22.0)**2)))
        hist=float(np.mean([self._bhattacharyya(a,b) for a,b in zip(q['lab_hist'],r['lab_hist'])]))
        color=0.62*mean_sim+0.38*hist
        orient=self._bhattacharyya(q['orient'],r['orient'])
        mag=self._bhattacharyya(q['mag_hist'],r['mag_hist'])
        lbp=self._bhattacharyya(q['lbp'],r['lbp'])
        rel=float(np.mean(np.abs(q['tex']-r['tex'])/np.maximum(np.maximum(q['tex'],r['tex']),0.01)))
        stats=max(0.0,1.0-rel)
        texture=0.24*orient+0.18*mag+0.30*lbp+0.28*stats
        raw=0.76*color+0.24*texture
        # V5.8: menos inflação de score. Textura nunca pode compensar cor errada.
        score=100.0*(max(0.0,min(1.0,raw))**0.92)
        tone_gate='ok'
        qL=float(q['l50']); rL=float(r['l50']); ldiff=abs(qL-rL)
        # Trava reforçada para superfícies neutras. Branco, cinza e preto não
        # podem ser "resgatados" por textura quando a luminosidade é incompatível.
        # V9 — COR PRIMEIRO. 'Neutro' só vale quando não existe evidência
        # cromática consistente de madeira quente. Isso corrige o caso real em que
        # uma chapa marrom sob iluminação fria ficou com muitos pixels de baixo chroma
        # e foi erroneamente tratada como cinza.
        q_warm_signal=bool(q.get('b75',0)>=7.0 or q.get('warm_frac5',0)>=0.34 or (q.get('b50',0)>=5.5 and q.get('chroma75',0)>=8.0))
        r_warm_signal=bool(r.get('b75',0)>=7.0 or r.get('warm_frac5',0)>=0.34 or (r.get('b50',0)>=5.5 and r.get('chroma75',0)>=8.0))
        q_neutral=bool(q.get('neutral_frac',0)>0.62 and q.get('contrast',99)<16 and not q_warm_signal)
        r_neutral=bool(r.get('neutral_frac',0)>0.62 and r.get('contrast',99)<16 and not r_warm_signal)
        # Trava de cromaticidade: superfície neutra não pode casar com referência
        # fortemente colorida e vice-versa. Isso impede branco/cinza de puxar madeira,
        # bege, marrom ou outras cores só por textura/ruído semelhante.
        q_ab=np.asarray(q['median_lab'],dtype=np.float32)[1:3]
        r_ab=np.asarray(r['median_lab'],dtype=np.float32)[1:3]
        q_chroma=float(np.linalg.norm(q_ab)); r_chroma=float(np.linalg.norm(r_ab))
        qa,qb=float(q_ab[0]),float(q_ab[1]); ra,rb=float(r_ab[0]),float(r_ab[1])

        # Família cromática ampla. Serve como trava física, não como classificador de SKU.
        # Ex.: uma chapa marrom/amadeirada não pode ser vencida por uma referência cinza
        # apenas porque os veios/gradientes são parecidos.
        q_warm_wood=bool(q_warm_signal or (q_chroma>=10.0 and qb>=7.0 and qa>=-3.0))
        r_warm_wood=bool(r_warm_signal or (r_chroma>=10.0 and rb>=7.0 and ra>=-3.0))
        q_neutral_family=bool(q_chroma<=8.5 and not q_warm_signal)
        r_neutral_family=bool(r_chroma<=8.5 and not r_warm_signal)
        q_cool=bool(q_chroma>=10.0 and qb<=2.0)
        r_cool=bool(r_chroma>=10.0 and rb<=2.0)
        # V9: incompatibilidade de família cromática é eliminatória antes da textura.
        # Madeira quente/marrom não pode perder para cinza/neutro só por padrão de veio.
        if q_warm_signal and (r.get('warm_frac5',0)<0.14 and r.get('b75',0)<5.0):
            score=min(score,24.0); tone_gate='color_family_mismatch'
        elif r_warm_signal and (q.get('warm_frac5',0)<0.14 and q.get('b75',0)<5.0):
            score=min(score,24.0); tone_gate='color_family_mismatch'
        elif q_warm_wood and r_neutral_family:
            score=min(score,32.0); tone_gate='warm_neutral_conflict'
        elif r_warm_wood and q_neutral_family:
            score=min(score,32.0); tone_gate='warm_neutral_conflict'
        elif (q_warm_wood and r_cool) or (r_warm_wood and q_cool):
            score=min(score,28.0); tone_gate='warm_cool_conflict'
        elif abs(qb-rb)>16 and max(q_chroma,r_chroma)>12:
            score=min(score,52.0); tone_gate='hue_family_conflict'
        if q_neutral and r_chroma>13.0:
            score=min(score,18.0); tone_gate='neutral_chroma_conflict'
        elif r_neutral and q_chroma>13.0:
            score=min(score,18.0); tone_gate='neutral_chroma_conflict'
        if q_neutral and r_neutral:
            if qL>=80 and rL<68:
                score=min(score,22.0); tone_gate='white_gray_conflict'
            elif rL>=80 and qL<68:
                score=min(score,22.0); tone_gate='white_gray_conflict'
            elif qL>=72 and rL<58:
                score=min(score,38.0); tone_gate='neutral_luminance_conflict'
            elif rL>=72 and qL<58:
                score=min(score,38.0); tone_gate='neutral_luminance_conflict'
            elif ldiff>16:
                score=min(score,58.0); tone_gate='neutral_luminance_far'
            elif ldiff>10:
                score=min(score,76.0); tone_gate='neutral_luminance_warning'
        if (qL>=70 and rL<=38) or (rL>=70 and qL<=38):
            score=min(score,12.0); tone_gate='light_dark_conflict'
        elif (q['white_frac']>=0.45 and r['dark_frac']>=0.45) or (r['white_frac']>=0.45 and q['dark_frac']>=0.45):
            score=min(score,16.0); tone_gate='white_dark_conflict'
        elif ldiff>42:
            score=min(score,28.0); tone_gate='luminance_conflict'
        elif ldiff>30:
            score=min(score,48.0); tone_gate='luminance_far'
        elif ldiff>22:
            score=min(score,66.0); tone_gate='luminance_warning'
        # Referência com fundo branco dominante não pode vencer uma foto de superfície
        # preenchida só porque bordas/gradientes coincidem. Foi a causa de MDF Cru com
        # foto de produto recortada superar um padrão madeirado real.
        q_white=float(q.get('white_frac',0)); r_white=float(r.get('white_frac',0))
        if r_white>=0.42 and q_white<=0.10:
            score=min(score,55.0); tone_gate='reference_background_mismatch'
        elif q_white>=0.42 and r_white<=0.10:
            score=min(score,55.0); tone_gate='query_background_mismatch'
        if delta>38: score=min(score,42.0); tone_gate='color_conflict'
        elif delta>28: score=min(score,62.0)
        elif delta>20: score=min(score,78.0)
        return {
            'score':round(float(score),2),'color':round(color*100,1),'texture':round(texture*100,1),
            'delta_e':round(delta,1),'delta_mean':round(delta_mean,1),'tone_gate':tone_gate,
            'query_l50':round(qL,1),'reference_l50':round(rL,1),
            'query_white':round(q['white_frac']*100,1),'reference_dark':round(r['dark_frac']*100,1),
            'query_b75':round(float(q.get('b75',0)),1),'reference_b75':round(float(r.get('b75',0)),1),
            'query_warm_fraction':round(float(q.get('warm_frac5',0))*100,1),'reference_warm_fraction':round(float(r.get('warm_frac5',0))*100,1),
            'query_color_family':'warm_wood' if q_warm_signal else ('neutral' if q_neutral else 'other'),
            'reference_color_family':'warm_wood' if r_warm_signal else ('neutral' if r_neutral else 'other')
        }

    def compare_images(self, query_path: str | Path, reference_path: str | Path) -> dict:
        try:
            q=self._verification_descriptor(query_path,query=True)
            return self.compare_query_descriptor(q,reference_path)
        except Exception:
            return {'score':0.0,'color':0.0,'texture':0.0,'delta_e':999.0,'tone_gate':'invalid'}

    def similarity(self, a: list[float], b: list[float]) -> float:
        va = np.asarray(a, dtype=np.float32)
        vb = np.asarray(b, dtype=np.float32)
        if va.size != vb.size or va.size == 0:
            return 0.0
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        if denom <= 1e-12:
            return 0.0
        cosine = float(np.dot(va, vb) / denom)
        cosine = max(-1.0, min(1.0, cosine))
        # Faixa visual mais útil: 0..100, sem transformar semelhanças moderadas em 90+.
        score = max(0.0, min(100.0, cosine * 100.0))
        return round(score, 2)

engine = VisionEngine()

def dumps_feature(v: list[float]) -> str:
    return json.dumps({"version": FEATURE_VERSION, "feature": v}, separators=(",", ":"))

def loads_feature(s: str) -> list[float]:
    obj = json.loads(s)
    if isinstance(obj, dict):
        return obj.get("feature") or []
    return obj if isinstance(obj, list) else []

def feature_is_current(s: str | None) -> bool:
    if not s:
        return False
    try:
        obj = json.loads(s)
        return isinstance(obj, dict) and int(obj.get("version") or 0) == FEATURE_VERSION and isinstance(obj.get("feature"), list)
    except Exception:
        return False
