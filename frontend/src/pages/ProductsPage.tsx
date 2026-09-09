import { useEffect, useRef, useState } from "react";
import { Search, ImagePlus, Plus, X, Video } from "lucide-react";
import { API, api } from "../api";

export function ProductsPage(){
  const [items,setItems]=useState<any[]>([]);
  const [q,setQ]=useState("");
  const [selected,setSelected]=useState<any>();
  const [showNew,setShowNew]=useState(false);
  const [form,setForm]=useState({sku:"",description:"",address:""});
  const photo=useRef<HTMLInputElement>(null);
  const video=useRef<HTMLInputElement>(null);

  const load=()=>api<any[]>(`/products?q=${encodeURIComponent(q)}`).then(setItems);
  useEffect(()=>{load()},[q]);

  async function save(){
    await api("/products",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(form)});
    setShowNew(false); setForm({sku:"",description:"",address:""}); load();
  }

  async function uploadMedia(f:File,type:string){
    if(!selected)return;
    const fd=new FormData(); fd.append("media_type",type); fd.append("file",f);
    await fetch(`${API}/products/${selected.sku}/media`,{method:"POST",body:fd});
    alert(type==="image"?"Foto cadastrada.":"Vídeo cadastrado.");
    load();
  }

  return <div className="stack">
    <div className="toolbar">
      <div className="search"><Search/><input value={q} onChange={e=>setQ(e.target.value)} placeholder="Buscar SKU, descrição ou endereço..."/></div>
      <button className="primary" onClick={()=>setShowNew(true)}><Plus/> Novo produto</button>
    </div>

    <div className="table-card">
      <table>
        <thead><tr><th>SKU</th><th>Descrição</th><th>Endereço</th><th>Fotos</th><th>Status</th><th></th></tr></thead>
        <tbody>{items.map(p=><tr key={p.sku}>
          <td><strong>{p.sku}</strong></td>
          <td>{p.description}</td>
          <td><span className="address-pill">{p.address}</span></td>
          <td>{p.photos}</td>
          <td><span className={`badge ${p.photos>=5?"ready":"pending"}`}>{p.photos>=5?"PRONTO":"CADASTRAR FOTOS"}</span></td>
          <td><button className="link-btn" onClick={()=>setSelected(p)}>Cadastro visual</button></td>
        </tr>)}</tbody>
      </table>
    </div>

    {selected && <div className="modal-backdrop">
      <div className="modal">
        <button className="modal-close" onClick={()=>setSelected(undefined)}><X/></button>
        <span className="eyebrow">CADASTRO VISUAL</span>
        <h2>{selected.sku}</h2>
        <p>{selected.description}</p>
        <div className="address-block mini"><small>ENDEREÇO</small><strong>{selected.address}</strong></div>
        <p className="helper">Cadastre 5 fotos diferentes e 1 vídeo curto para formar uma base visual consistente.</p>
        <input ref={photo} hidden type="file" accept="image/*" capture="environment" onChange={e=>e.target.files?.[0]&&uploadMedia(e.target.files[0],"image")}/>
        <input ref={video} hidden type="file" accept="video/*" capture="environment" onChange={e=>e.target.files?.[0]&&uploadMedia(e.target.files[0],"video")}/>
        <button className="primary full" onClick={()=>photo.current?.click()}><ImagePlus/> Adicionar foto</button>
        <button className="secondary full" onClick={()=>video.current?.click()}><Video/> Adicionar vídeo</button>
      </div>
    </div>}

    {showNew && <div className="modal-backdrop">
      <div className="modal">
        <button className="modal-close" onClick={()=>setShowNew(false)}><X/></button>
        <h2>Novo produto</h2>
        <label>SKU<input value={form.sku} onChange={e=>setForm({...form,sku:e.target.value})}/></label>
        <label>Descrição<input value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/></label>
        <label>Endereço<input value={form.address} onChange={e=>setForm({...form,address:e.target.value})}/></label>
        <button className="primary full" onClick={save}>Salvar produto</button>
      </div>
    </div>}
  </div>
}
