import { useEffect, useState } from "react";
import {
  Camera, Boxes, Upload, History, LayoutDashboard, Settings, ScanLine,
  Printer, Home, Menu, X, ChevronRight, Globe2
} from "lucide-react";
import { api } from "./api";
import { HomePage } from "./pages/HomePage";
import { IdentifyPage } from "./pages/IdentifyPage";
import { ProductsPage } from "./pages/ProductsPage";
import { ImportPage } from "./pages/ImportPage";
import { HistoryPage } from "./pages/HistoryPage";
import { LoginPage } from "./pages/LoginPage";
import { CatalogPage } from "./pages/CatalogPage";
import { SettingsPage } from "./pages/SettingsPage";

type Page = "home"|"identify"|"catalog"|"products"|"import"|"history"|"settings";

const items = [
  ["home", Home, "Início"],
  ["identify", ScanLine, "Identificar"],
  ["catalog", Globe2, "Catálogo Leo"],
  ["products", Boxes, "Produtos"],
  ["import", Upload, "Importar Base"],
  ["history", History, "Histórico"],
  ["settings", Settings, "Configurações"],
] as const;

export function App() {
  const [page,setPage] = useState<Page>("home");
  const [mobile,setMobile] = useState(false);
  const [health,setHealth] = useState("...");
  const [auth,setAuth] = useState<"loading"|"yes"|"no">("loading");

  const checkAuth=()=>{
    fetch("/auth/me",{credentials:"include"})
      .then(r=>{ if(!r.ok) throw new Error(); return r.json(); })
      .then(()=>{setAuth("yes"); api<any>("/health").then(()=>setHealth("Online")).catch(()=>setHealth("Offline"));})
      .catch(()=>setAuth("no"));
  };

  useEffect(()=>{ checkAuth(); },[]);

  if(auth==="loading") return <div className="boot-screen"><div className="spinner"></div><strong>CHAPA ID</strong><span>Carregando ambiente seguro...</span></div>;
  if(auth==="no") return <LoginPage onLogin={checkAuth}/>;

  const render = () => {
    if(page==="home") return <HomePage go={setPage}/>;
    if(page==="identify") return <IdentifyPage/>;
    if(page==="catalog") return <CatalogPage/>;
    if(page==="products") return <ProductsPage/>;
    if(page==="import") return <ImportPage/>;
    if(page==="settings") return <SettingsPage/>;
    return <HistoryPage/>;
  };

  return <div className="app-shell">
    <aside className={`sidebar ${mobile?"open":""}`}>
      <div className="brand">
        <div className="brandmark"><ScanLine size={22}/></div>
        <div><strong>CHAPA ID</strong><small>Identificação Inteligente</small></div>
        <button className="mobile-close" onClick={()=>setMobile(false)}><X/></button>
      </div>
      <nav>
        {items.map(([key,Icon,label])=>
          <button className={page===key?"active":""} key={key} onClick={()=>{setPage(key);setMobile(false)}}>
            <Icon size={19}/><span>{label}</span>{key==="identify" && <ChevronRight size={17} className="nav-right"/>}
          </button>
        )}
      </nav>
      <div className="sidebar-bottom">
        <div className={`status-dot ${health==="Online"?"ok":""}`}></div>
        <div><small>Sistema</small><strong>{health}</strong></div>
      </div>
    </aside>

    <main>
      <header className="topbar">
        <button className="menu-btn" onClick={()=>setMobile(true)}><Menu/></button>
        <div>
          <h1>{items.find(i=>i[0]===page)?.[2]}</h1>
          <p>Identificação de chapas por visão computacional</p>
        </div>
        <div className="user-chip"><span>CC</span><div><strong>Caio Cezar</strong><small>Administrador</small></div></div>
      </header>
      <section className="content">{render()}</section>
    </main>
  </div>
}
