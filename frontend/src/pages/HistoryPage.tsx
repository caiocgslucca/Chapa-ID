import { useEffect, useState } from "react";
import { api } from "../api";

export function HistoryPage(){
  const [items,setItems]=useState<any[]>([]);
  useEffect(()=>{api<any[]>("/history").then(setItems)},[]);
  return <div className="table-card">
    <table>
      <thead><tr><th>Data/Hora</th><th>SKU sugerido</th><th>SKU confirmado</th><th>Confiança</th><th>Status</th><th>Operador</th></tr></thead>
      <tbody>{items.map(i=><tr key={i.id}>
        <td>{i.created_at}</td><td><strong>{i.suggested_sku||"-"}</strong></td><td>{i.confirmed_sku||"-"}</td>
        <td>{i.score?.toFixed?.(1) ?? i.score}%</td><td><span className={`badge ${i.status==="high"?"ready":"pending"}`}>{i.status}</span></td><td>{i.operator}</td>
      </tr>)}</tbody>
    </table>
  </div>
}
