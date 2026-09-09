import { useEffect, useState } from "react";
import { Camera, Boxes, CheckCircle2, Target, ArrowRight, Upload, History, Globe2 } from "lucide-react";
import { api } from "../api";

export function HomePage({go}:{go:(p:any)=>void}) {
  const [d,setD]=useState({products:0,ready:0,identifications:0,accuracy:0,catalog_products:0,catalog_images:0});
  useEffect(()=>{api<any>("/dashboard").then(setD).catch(()=>{})},[]);
  return <div className="stack">
    <section className="hero">
      <div>
        <span className="eyebrow">VISÃO COMPUTACIONAL</span>
        <h2>Identifique a chapa em segundos.</h2>
        <p>Fotografe o produto e compare a chapa física com o catálogo Leo e com as fotos já confirmadas.</p>
        <button className="primary big" onClick={()=>go("identify")}><Camera/> Abrir câmera <ArrowRight/></button>
      </div>
      <div className="hero-visual"><div className="scan-frame"><span></span></div></div>
    </section>

    <div className="metrics">
      <div className="metric"><Boxes/><div><small>Produtos</small><strong>{d.products}</strong></div></div>
      <div className="metric"><CheckCircle2/><div><small>Prontos</small><strong>{d.ready}</strong></div></div>
      <div className="metric"><Camera/><div><small>Identificações</small><strong>{d.identifications}</strong></div></div>
      <div className="metric"><Target/><div><small>Taxa de acerto</small><strong>{d.accuracy}%</strong></div></div>
    </div>

    <div className="quick-grid">
      <button className="quick" onClick={()=>go("catalog")}><Globe2/><span>Catálogo Leo</span><small>{d.catalog_products} SKUs sincronizados</small></button>
      <button className="quick" onClick={()=>go("products")}><Boxes/><span>Produtos</span><small>Cadastro e imagens</small></button>
      <button className="quick" onClick={()=>go("import")}><Upload/><span>Importar Base</span><small>SKU, descrição e endereço</small></button>
      <button className="quick" onClick={()=>go("history")}><History/><span>Histórico</span><small>Consultas e confirmações</small></button>
    </div>
  </div>
}
