import { useEffect, useRef, useState } from "react";
import { Camera, UploadCloud, CheckCircle2, AlertTriangle, XCircle, Printer, Globe2, BrainCircuit, ExternalLink, X, MapPin, Layers3, ScanLine, Square } from "lucide-react";
import { API } from "../api";
const pct=(n:any)=>`${Number(n||0).toLocaleString("pt-BR",{minimumFractionDigits:1,maximumFractionDigits:1})}%`;
const missingAddress=(v?:string)=>!v||["não informado","nao informado","localização pendente de cadastro"].includes(v.trim().toLowerCase());
const scoreClass=(n:any)=>{const v=Number(n||0);return v>=90?"score-excellent":v>=75?"score-good":v>=60?"score-medium":"score-low"};

export function IdentifyPage(){
  const input=useRef<HTMLInputElement>(null);
  const uploadInput=useRef<HTMLInputElement>(null);
  const videoRef=useRef<HTMLVideoElement>(null);
  const streamRef=useRef<MediaStream|null>(null);
  const trackRef=useRef<MediaStreamTrack|null>(null);
  const scanTimerRef=useRef<number|undefined>(undefined);
  const stableRef=useRef<{sku?:string,count:number}>({count:0});
  const lightStableRef=useRef(0);
  const lightCalibratedRef=useRef(false);
  const autoLightRef=useRef<{torch:boolean,lastAdjust:number}>({torch:false,lastAdjust:0});
  const scanStartedRef=useRef(0);
  const bestFrameRef=useRef<{file:File,score:number,sku?:string,quality:number,metrics?:{mean:number,dark:number,bright:number,std:number,colorSpread:number}}|null>(null);
  const scanEvidenceRef=useRef<Record<string,{scores:number[],best:number,file:File,metrics:{mean:number,dark:number,bright:number,std:number,colorSpread:number},info:any}>>({});
  const scanFramesRef=useRef<Array<{file:File,metrics:{mean:number,dark:number,bright:number,std:number,colorSpread:number},signature:number[],quality:number}>>([]);
  const lastSignatureRef=useRef<number[]|null>(null);
  const finalizingRef=useRef(false);
  const preTorchMetricsRef=useRef<{mean:number,dark:number,bright:number,std:number,colorSpread:number}|null>(null);
  const lightGainRef=useRef(0);
  const lightValidatedRef=useRef(false);
  const [preview,setPreview]=useState<string>();
  const [loading,setLoading]=useState(false);
  const [scanning,setScanning]=useState(false);
  const [scanStatus,setScanStatus]=useState("Aguardando câmera...");
  const [scanCount,setScanCount]=useState(0);
  const [scanCoverage,setScanCoverage]=useState(0);
  const [scanDiversity,setScanDiversity]=useState(0);
  const [scanColorStability,setScanColorStability]=useState(0);
  const [data,setData]=useState<any>();
  const [confirmed,setConfirmed]=useState<string>();
  const [zoom,setZoom]=useState<{url:string,label:string,description?:string}>();

  function stopScanner(){
    if(scanTimerRef.current)window.clearTimeout(scanTimerRef.current);
    scanTimerRef.current=undefined;
    streamRef.current?.getTracks().forEach(t=>t.stop());
    streamRef.current=null;trackRef.current=null;
    stableRef.current={count:0};lightStableRef.current=0;lightCalibratedRef.current=false;autoLightRef.current={torch:false,lastAdjust:0};scanStartedRef.current=0;bestFrameRef.current=null;scanEvidenceRef.current={};scanFramesRef.current=[];lastSignatureRef.current=null;finalizingRef.current=false;preTorchMetricsRef.current=null;lightGainRef.current=0;lightValidatedRef.current=false;
    setScanning(false);
  }
  useEffect(()=>()=>stopScanner(),[]);

  async function analyzeFile(f:File,fromScanner=false,fastScan=false,softwareNormalized=false,originalMetrics?:{mean:number,dark:number,bright:number,std:number,colorSpread:number},scannerContext=false,inputSource="camera"){
    if(!fromScanner){stopScanner();setPreview(URL.createObjectURL(f));setData(undefined);setConfirmed(undefined)}
    setLoading(true);
    const fd=new FormData();fd.append("file",f);fd.append("operator","Caio Cezar");fd.append("input_source",inputSource);
    if(fromScanner)fd.append("ephemeral","1");
    if((fromScanner||scannerContext)&&lightCalibratedRef.current&&lightValidatedRef.current)fd.append("controlled_light","1");
    if(fastScan)fd.append("scan_mode","fast");
    if(softwareNormalized)fd.append("software_normalized","1");
    if(originalMetrics){
      fd.append("original_mean",String(originalMetrics.mean));
      fd.append("original_dark",String(originalMetrics.dark));
      fd.append("original_std",String(originalMetrics.std));
      fd.append("original_color_spread",String(originalMetrics.colorSpread));
    }
    if(fromScanner||scannerContext){
      fd.append("light_gain",String(lightGainRef.current||0));
      fd.append("light_validated",lightValidatedRef.current?"1":"0");
    }
    const controller=new AbortController();
    const timeout=window.setTimeout(()=>controller.abort(),fastScan?6500:36000);
    try{
      const r=await fetch(`${API}/identify`,{method:"POST",body:fd,signal:controller.signal});
      const x=await r.json();
      if(!r.ok)throw new Error(x.detail||"Falha ao analisar imagem.");
      if(!fromScanner)setData(x);
      return x;
    }catch(e:any){
      const msg=e?.name==="AbortError"?"Análise excedeu o tempo desta leitura; tentando próximo quadro...":(e?.message||"Falha ao analisar imagem.");
      if(!fromScanner)setData({error:msg,results:[]});
      return {error:msg,transient:e?.name==="AbortError",results:[]};
    }finally{window.clearTimeout(timeout);setLoading(false)}
  }

  async function fileToCanvas(file:File){
    const url=URL.createObjectURL(file);
    try{
      const img=await new Promise<HTMLImageElement>((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src=url});
      const c=document.createElement("canvas");const maxW=1600;const scale=Math.min(1,maxW/Math.max(img.naturalWidth,1));
      c.width=Math.max(1,Math.round(img.naturalWidth*scale));c.height=Math.max(1,Math.round(img.naturalHeight*scale));
      c.getContext("2d")?.drawImage(img,0,0,c.width,c.height);return c;
    }finally{URL.revokeObjectURL(url)}
  }

  function enhanceForEnvironment(source:HTMLCanvasElement){
    const out=document.createElement("canvas");out.width=source.width;out.height=source.height;
    const ctx=out.getContext("2d",{willReadFrequently:true});if(!ctx)return {canvas:source,changed:false};
    ctx.drawImage(source,0,0);const m=lightMetrics(source);
    // Correção limitada: melhora leitura em sombra sem "inventar" a cor do produto.
    // O ganho máximo é deliberadamente contido e o backend continua aplicando travas físicas.
    let gamma=1.0;
    if(m.mean<.22)gamma=.58;else if(m.mean<.32)gamma=.68;else if(m.mean<.42)gamma=.80;else if(m.mean>.90)gamma=1.18;
    const needs=Math.abs(gamma-1)>.02||m.colorSpread>.10;
    if(!needs)return {canvas:source,changed:false};
    const im=ctx.getImageData(0,0,out.width,out.height),d=im.data;
    let sr=0,sg=0,sb=0,n=0;for(let i=0;i<d.length;i+=16){sr+=d[i];sg+=d[i+1];sb+=d[i+2];n++}
    const avg=(sr+sg+sb)/Math.max(3*n,1);const gains=[avg/Math.max(sr/Math.max(n,1),1),avg/Math.max(sg/Math.max(n,1),1),avg/Math.max(sb/Math.max(n,1),1)].map(g=>Math.max(.88,Math.min(1.14,g)));
    for(let i=0;i<d.length;i+=4){for(let c=0;c<3;c++){let v=Math.max(0,Math.min(1,(d[i+c]/255)*gains[c]));v=Math.pow(v,gamma);d[i+c]=Math.max(0,Math.min(255,Math.round(v*255)))}}
    ctx.putImageData(im,0,0);return {canvas:out,changed:true};
  }

  async function canvasToFile(canvas:HTMLCanvasElement,name:string){const blob=await new Promise<Blob|null>(res=>canvas.toBlob(res,"image/jpeg",0.91));return blob?new File([blob],name,{type:"image/jpeg"}):null}

  async function identifyCamera(f:File){
    try{
      const raw=await fileToCanvas(f);
      const original=lightMetrics(raw);
      const enhanced=enhanceForEnvironment(raw);
      const prepared=await canvasToFile(enhanced.canvas,`foto-${Date.now()}.jpg`);
      await analyzeFile(prepared||f,false,false,enhanced.changed,original);
    }catch{await analyzeFile(f,false,false,false)}
  }

  async function identifyExisting(f:File){
    // Arquivo existente usa pixels originais. Não aplicamos correção de ambiente,
    // pois uma imagem do catálogo deve poder ser reconhecida por identidade perceptual.
    await analyzeFile(f,false,false,false,undefined,false,"upload");
  }

  function lightMetrics(canvas:HTMLCanvasElement){
    const ctx=canvas.getContext("2d",{willReadFrequently:true});
    if(!ctx)return {mean:0,dark:1,bright:0,std:0,colorSpread:0};
    const w=Math.min(160,canvas.width),h=Math.min(120,canvas.height);
    const sample=document.createElement("canvas");sample.width=w;sample.height=h;
    const sc=sample.getContext("2d",{willReadFrequently:true});
    if(!sc)return {mean:0,dark:1,bright:0,std:0,colorSpread:0};
    sc.drawImage(canvas,0,0,w,h);
    const d=sc.getImageData(0,0,w,h).data;let sum=0,sum2=0,dark=0,bright=0,n=0;let sr=0,sg=0,sb=0;
    for(let i=0;i<d.length;i+=4){const r=d[i]/255,g=d[i+1]/255,b=d[i+2]/255;const y=0.2126*r+0.7152*g+0.0722*b;sum+=y;sum2+=y*y;sr+=r;sg+=g;sb+=b;n++;if(y<.22)dark++;if(y>.96)bright++;}
    const mean=sum/Math.max(n,1),variance=Math.max(0,sum2/Math.max(n,1)-mean*mean);
    const mr=sr/Math.max(n,1),mg=sg/Math.max(n,1),mb=sb/Math.max(n,1);
    return {mean,dark:dark/Math.max(n,1),bright:bright/Math.max(n,1),std:Math.sqrt(variance),colorSpread:Math.max(mr,mg,mb)-Math.min(mr,mg,mb)};
  }

  async function autoCorrectLight(m:{mean:number,dark:number,bright:number,std:number,colorSpread:number}){
    const track:any=trackRef.current;
    if(!track)return {ready:true,controlled:false,neutralLowLight:false,hardware:false};

    const now=Date.now();
    const neutral=m.std<.11&&m.colorSpread<.095;
    const lowLight=m.mean<.64||m.dark>.24;
    const veryDark=m.mean<.34||m.dark>.62;
    const tooBright=m.mean>.92||m.bright>.13;
    const needsPhysicalLight=neutral&&lowLight;

    if(now-autoLightRef.current.lastAdjust<420){
      return {ready:false,controlled:lightValidatedRef.current,neutralLowLight:needsPhysicalLight,hardware:true};
    }
    autoLightRef.current.lastAdjust=now;

    try{
      const caps:any=track.getCapabilities?.()||{};
      const settings:any=track.getSettings?.()||{};
      const torchSupported=Array.isArray(caps.torch)?caps.torch.includes(true):caps.torch===true;

      // Guarda a leitura ANTES da iluminação. A validação só acontece se a imagem
      // realmente ficar mais clara depois do torch.
      if(needsPhysicalLight && !preTorchMetricsRef.current){
        preTorchMetricsRef.current={...m};
      }

      if((needsPhysicalLight||veryDark) && torchSupported && !autoLightRef.current.torch){
        setScanStatus("Ambiente escuro • ativando iluminação física da câmera...");
        await track.applyConstraints({advanced:[{torch:true}]});
        autoLightRef.current.torch=true;
        lightStableRef.current=0;
        lightCalibratedRef.current=false;
        return {ready:false,controlled:false,neutralLowLight:true,hardware:true};
      }

      if(autoLightRef.current.torch && preTorchMetricsRef.current){
        const before=preTorchMetricsRef.current;
        const gain=m.mean-before.mean;
        lightGainRef.current=Math.max(lightGainRef.current,gain);
        const darkerPixelsImproved=(before.dark-m.dark)>0.06;
        const realGain=gain>=0.055 || darkerPixelsImproved;

        if(realGain){
          lightStableRef.current++;
          if(lightStableRef.current>=3){
            lightValidatedRef.current=true;
            lightCalibratedRef.current=true;
            setScanStatus(`Iluminação validada • ganho ${(lightGainRef.current*100).toFixed(0)}% • medindo cor real...`);
            return {ready:true,controlled:true,neutralLowLight:false,hardware:true};
          }
          setScanStatus("Iluminação física ativa • estabilizando exposição e balanço de branco...");
          return {ready:false,controlled:false,neutralLowLight:true,hardware:true};
        }
      }

      // Aumenta exposição do sensor quando torch não existe ou ainda não bastou.
      const exp=caps.exposureCompensation;
      if((lowLight||veryDark) && exp && typeof exp.min==="number" && typeof exp.max==="number"){
        const step=Math.max(Number(exp.step||.25),.1);
        const cur=Number(settings.exposureCompensation??0);
        const next=Math.min(Number(exp.max),cur+step*(veryDark?2:1));
        if(next>cur+.001){
          setScanStatus("Ajustando exposição óptica do sensor...");
          await track.applyConstraints({advanced:[{exposureCompensation:next}]});
          return {ready:false,controlled:false,neutralLowLight:needsPhysicalLight,hardware:true};
        }
      }

      if(tooBright && autoLightRef.current.torch){
        await track.applyConstraints({advanced:[{torch:false}]});
        autoLightRef.current.torch=false;
        lightValidatedRef.current=false;
        lightCalibratedRef.current=false;
        preTorchMetricsRef.current=null;
        return {ready:false,controlled:false,neutralLowLight:false,hardware:true};
      }

      if(!needsPhysicalLight && !tooBright){
        lightStableRef.current++;
        return {ready:lightStableRef.current>=2,controlled:lightValidatedRef.current,neutralLowLight:false,hardware:true};
      }

      if(needsPhysicalLight && !torchSupported){
        setScanStatus("Superfície branca/cinza/preta em pouca luz • buscando exposição segura...");
        return {ready:false,controlled:false,neutralLowLight:true,hardware:false};
      }
    }catch{}

    return {ready:false,controlled:false,neutralLowLight:needsPhysicalLight,hardware:false};
  }

  function frameSignature(canvas:HTMLCanvasElement){
    const sample=document.createElement("canvas");sample.width=3;sample.height=3;
    const ctx=sample.getContext("2d",{willReadFrequently:true});if(!ctx)return [0,0,0,0,0,0,0,0,0];
    ctx.drawImage(canvas,0,0,3,3);const d=ctx.getImageData(0,0,3,3).data;const out:number[]=[];
    for(let i=0;i<d.length;i+=4)out.push((0.2126*d[i]+0.7152*d[i+1]+0.0722*d[i+2])/255);
    return out;
  }

  function signatureDistance(a:number[]|null,b:number[]){
    if(!a||a.length!==b.length)return 1;let sum=0;for(let i=0;i<b.length;i++)sum+=Math.abs(a[i]-b[i]);return sum/b.length;
  }

  async function finalizeScannerSession(){
    if(finalizingRef.current)return;
    const frames=[...scanFramesRef.current];
    if(frames.length<4){
      setScanStatus(`Cobertura insuficiente: ${frames.length} região(ões). Percorra mais áreas da chapa antes de finalizar.`);
      return;
    }
    finalizingRef.current=true;
    if(scanTimerRef.current)window.clearTimeout(scanTimerRef.current);scanTimerRef.current=undefined;
    setScanStatus(`Motor Visual Industrial • consolidando ${frames.length} regiões distintas...`);

    // Escolhe até 4 keyframes espacialmente diferentes. Cada um passa por análise
    // completa; o vencedor precisa aparecer de forma consistente em várias regiões.
    const selected=frames.slice(-12).filter((_,i,a)=>i===0||i===a.length-1||i%Math.max(1,Math.floor(a.length/4))===0).slice(0,4);
    const analyses:any[]=[];
    for(let i=0;i<selected.length;i++){
      setScanStatus(`Verificação industrial ${i+1}/${selected.length} • comparando outra região do padrão...`);
      const x=await analyzeFile(selected[i].file,true,false,true,selected[i].metrics,true);
      if(x&&!x.error&&Array.isArray(x.results))analyses.push(x);
    }
    if(!analyses.length){finalizingRef.current=false;setScanStatus("Nenhuma região passou pela verificação completa. Melhore iluminação/foco e tente novamente.");return}

    const consensus:Record<string,{points:number,scores:number[],hits:number}>={};
    analyses.forEach(a=>{
      (a.results||[]).slice(0,4).forEach((r:any,idx:number)=>{
        const sku=String(r.sku||"");if(!sku)return;
        const sc=Number(r.visual_score??r.score??0);
        if(!consensus[sku])consensus[sku]={points:0,scores:[],hits:0};
        consensus[sku].points+=Math.max(0,4-idx)*Math.max(0,sc-45);
        consensus[sku].scores.push(sc);
        consensus[sku].hits++;
      });
    });
    const ranked=Object.entries(consensus).map(([sku,v])=>{
      const med=[...v.scores].sort((a,b)=>a-b)[Math.floor(v.scores.length/2)]||0;
      const support=v.hits/analyses.length;
      return {sku,...v,median:med,support,industrial:v.points*(.65+.35*support)};
    }).sort((a,b)=>b.industrial-a.industrial);
    const winner=ranked[0];
    if(!winner||winner.hits<2||winner.support<.5){
      setData({results:[],rejection_reason:"As regiões da chapa não produziram um candidato consistente. O V10 recusou uma identificação baseada em coincidência isolada.",industrial_session:{regions:frames.length,analysed:analyses.length,consensus:false}});
      stopScanner();return;
    }

    // Usa para registro final a região em que o SKU consensual teve maior evidência.
    let chosen=selected[0];let chosenScore=-1;
    analyses.forEach((a,idx)=>{const hit=(a.results||[]).find((r:any)=>String(r.sku)===winner.sku);const sc=Number(hit?.visual_score??hit?.score??0);if(sc>chosenScore){chosenScore=sc;chosen=selected[Math.min(idx,selected.length-1)]}});
    setScanStatus(`Consenso visual ${winner.sku} em ${(winner.support*100).toFixed(0)}% das regiões • executando decisão final...`);
    const final=await analyzeFile(chosen.file,false,false,true,chosen.metrics,true);
    if(final&&!final.error){
      const arr=[...(final.results||[])];
      arr.sort((a:any,b:any)=>{const aa=ranked.find(x=>x.sku===String(a.sku));const bb=ranked.find(x=>x.sku===String(b.sku));return (bb?.industrial||0)-(aa?.industrial||0)});
      arr.forEach((r:any,i:number)=>r.rank=i+1);
      final.results=arr;
      final.industrial_session={regions_captured:frames.length,regions_analysed:analyses.length,consensus_sku:winner.sku,consensus_support:Math.round(winner.support*1000)/10,median_score:Math.round(winner.median*10)/10,position_invariant:true,decision_policy:"multi_region_consensus"};
      fetch(`${API}/industrial/scan-session`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({operator:"Caio Cezar",regions_captured:frames.length,regions_used:analyses.length,color_stability:scanColorStability,visual_diversity:scanDiversity,consensus_sku:winner.sku,consensus_confidence:Math.round(winner.support*1000)/10,decision_mode:"multi_region_consensus",payload:{median_score:winner.median,ranked:ranked.slice(0,5)}})}).catch(()=>{});
      setData({...final});
    }
  }

  async function finalizeBestFrame(reason:string){
    if(finalizingRef.current)return;finalizingRef.current=true;
    const best=bestFrameRef.current;
    if(!best){setScanStatus("Não consegui uma captura utilizável. Aproxime a chapa e tente novamente.");stopScanner();return}
    setScanStatus(`${reason} • executando análise final...`);
    await analyzeFile(best.file,false,false,true,best.metrics,true);
  }

  async function scanFrame(){
    if(!streamRef.current||!videoRef.current||finalizingRef.current)return;
    const v=videoRef.current;
    if(v.readyState<2){scanTimerRef.current=window.setTimeout(scanFrame,250);return}
    const elapsed=Date.now()-scanStartedRef.current;
    if(elapsed>90000){setScanStatus("Varredura longa: finalize quando a cobertura estiver suficiente ou cancele para recomeçar.");}

    const canvas=document.createElement("canvas");const cropRatio=.74;
    const sw=Math.max(1,Math.round(v.videoWidth*cropRatio)),sh=Math.max(1,Math.round(v.videoHeight*cropRatio));
    const sx=Math.round((v.videoWidth-sw)/2),sy=Math.round((v.videoHeight-sh)/2);const maxW=1280,scale=Math.min(1,maxW/Math.max(sw,1));
    canvas.width=Math.max(640,Math.round(sw*scale));canvas.height=Math.max(480,Math.round(sh*scale));
    const ctx=canvas.getContext("2d");if(!ctx){stopScanner();return}ctx.drawImage(v,sx,sy,sw,sh,0,0,canvas.width,canvas.height);

    const lm=lightMetrics(canvas);const lightState=await autoCorrectLight(lm);
    // Superfície neutra em pouca luz NUNCA usa fallback de software como prova de cor.
    // Se o aparelho não tem torch/exposição suficiente, encerramos com orientação
    // em vez de devolver um SKU cinza para uma chapa branca.
    if(lightState.neutralLowLight&&!lightState.controlled){
      // Superfícies neutras (branco/cinza/preto) são fisicamente ambíguas sem
      // iluminação validada. IA não pode reconstruir a refletância real a partir de
      // uma foto subexposta. Continuamos tentando torch/exposição e, se não houver
      // ganho validado, bloqueamos em vez de exibir um SKU de cor errada.
      if(elapsed>10500&&!lightValidatedRef.current){
        setScanStatus("Não foi possível validar a cor real • aproxime a câmera e use iluminação/flash");
      }
      scanTimerRef.current=window.setTimeout(scanFrame,320);return;
    }
    const allowSoftwareFallback=elapsed>2500&&!lightState.neutralLowLight;
    if(!lightState.ready&&!allowSoftwareFallback){scanTimerRef.current=window.setTimeout(scanFrame,260);return}
    const enhanced=lightValidatedRef.current?{canvas,changed:false}:enhanceForEnvironment(canvas);
    const file=await canvasToFile(enhanced.canvas,`scan-${Date.now()}.jpg`);
    if(!file){scanTimerRef.current=window.setTimeout(scanFrame,350);return}

    const sig=frameSignature(enhanced.canvas);const distinct=signatureDistance(lastSignatureRef.current,sig)>=0.035;
    if(distinct){
      lastSignatureRef.current=sig;scanFramesRef.current.push({file,metrics:lm,signature:sig,quality:0});if(scanFramesRef.current.length>18)scanFramesRef.current.shift();
      const fs=scanFramesRef.current;const coverage=Math.min(100,Math.round((fs.length/10)*100));
      let div=0;if(fs.length>1){for(let i=1;i<fs.length;i++)div+=signatureDistance(fs[i-1].signature,fs[i].signature);div/=fs.length-1}
      const means=fs.map(x=>x.metrics.mean);const meanAvg=means.reduce((a,b)=>a+b,0)/Math.max(1,means.length);const colorVar=Math.sqrt(means.reduce((a,b)=>a+(b-meanAvg)*(b-meanAvg),0)/Math.max(1,means.length));
      setScanCoverage(coverage);setScanDiversity(Math.min(100,Math.round(div*900)));setScanColorStability(Math.max(0,Math.min(100,Math.round((1-Math.min(.25,colorVar)/.25)*100))));
    }

    setScanCount(n=>n+1);setScanStatus(enhanced.changed?"Ambiente corrigido • analisando nova região da chapa...":"Mapeando textura e cor desta região...");
    const x=await analyzeFile(file,true,true,enhanced.changed,lm);
    if(x?.transient){scanTimerRef.current=window.setTimeout(scanFrame,260);return}
    const top=x?.results?.[0];const visual=Number(x?.primary_score??x?.visual_score??top?.visual_score??top?.score??0);const q=Number(x?.capture_quality?.quality??0);
    const composite=(visual*.80)+(q*.20);
    if(!bestFrameRef.current||composite>bestFrameRef.current.score)bestFrameRef.current={file,score:composite,sku:top?.sku,quality:q,metrics:lm};

    // Consolidação multi-região: o scanner NÃO encerra sozinho. O operador percorre
    // a chapa inteira e clica em Finalizar scanner. Cada região adiciona evidência
    // para o mesmo SKU, permitindo capturar desenhos que aparecem em pontos distintos.
    for(const r of (x?.results||[]).slice(0,4)){
      const score=Number(r?.visual_score??r?.score??0);if(!r?.sku||score<52)continue;
      const key=String(r.sku);const prev=scanEvidenceRef.current[key];
      if(!prev)scanEvidenceRef.current[key]={scores:[score],best:score,file,metrics:lm,info:r};
      else{prev.scores.push(score);if(prev.scores.length>24)prev.scores.shift();if(score>prev.best){prev.best=score;prev.file=file;prev.metrics=lm;prev.info=r}}
    }
    const ranked=Object.entries(scanEvidenceRef.current).map(([sku,e])=>({sku,best:e.best,count:e.scores.length,avg:e.scores.slice(-4).reduce((a,b)=>a+b,0)/Math.max(1,e.scores.slice(-4).length)})).sort((a,b)=>(b.best+b.avg*.25+b.count)-(a.best+a.avg*.25+a.count));
    const lead=ranked[0];
    const regions=scanFramesRef.current.length;
    setScanStatus(lead?`V10 Industrial • ${regions} regiões • cobertura ${Math.min(100,Math.round(regions/10*100))}% • melhor evidência ${lead.sku} ${pct(lead.best)} • continue cobrindo áreas diferentes`:`V10 Industrial • ${regions} regiões • mova lentamente por centro, bordas e regiões com desenhos diferentes`);
    scanTimerRef.current=window.setTimeout(scanFrame,420);
  }

  async function startScanner(){
    try{
      stopScanner();setData(undefined);setPreview(undefined);setConfirmed(undefined);setScanCount(0);setScanCoverage(0);setScanDiversity(0);setScanColorStability(0);bestFrameRef.current=null;scanEvidenceRef.current={};scanFramesRef.current=[];lastSignatureRef.current=null;finalizingRef.current=false;
      setScanStatus("Abrindo câmera...");
      const stream=await navigator.mediaDevices.getUserMedia({
        video:{facingMode:{ideal:"environment"},width:{ideal:1280},height:{ideal:720},frameRate:{ideal:24,max:30}},audio:false
      });
      streamRef.current=stream;trackRef.current=stream.getVideoTracks()[0]||null;setScanning(true);
      // Ajuste automático do ambiente quando o navegador/câmera suportar.
      try{
        const track=trackRef.current as any;
        const caps=track?.getCapabilities?.()||{};
        const advanced:any={};
        if(caps.focusMode?.includes?.("continuous"))advanced.focusMode="continuous";
        if(caps.exposureMode?.includes?.("continuous"))advanced.exposureMode="continuous";
        if(caps.whiteBalanceMode?.includes?.("continuous"))advanced.whiteBalanceMode="continuous";
        if(Object.keys(advanced).length)await track.applyConstraints({advanced:[advanced]});
        // IMPORTANTE: não ligamos o torch aqui. O autoCorrectLight precisa primeiro
        // medir um quadro SEM iluminação e só depois acender o torch. Sem esse baseline
        // não existe validação fotométrica real e uma chapa branca pode virar cinza.
        // O torch será acionado automaticamente após a primeira medição estável.
      }catch{}
      requestAnimationFrame(async()=>{
        if(videoRef.current){
          videoRef.current.srcObject=stream;
          await videoRef.current.play().catch(()=>{});
          scanStartedRef.current=Date.now();
          setScanStatus("Calibrando câmera e iluminação...");
          scanTimerRef.current=window.setTimeout(scanFrame,900);
        }
      });
    }catch(e:any){
      stopScanner();
      setData({error:`Não foi possível abrir a câmera: ${e?.message||"permissão negada"}`,results:[]});
    }
  }
  async function confirm(sku:string){const r=await fetch(`${API}/identifications/${data.identification_id}/confirm`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({confirmed_sku:sku,operator:"Caio Cezar"})});const x=await r.json();if(r.ok)setConfirmed(sku);if(x.learned)data.learned=true}
  async function print(sku:string){const r=await fetch(`${API}/print`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sku,quantity:1})});const x=await r.json();alert(x.message||"Etiqueta enviada.")}
  const top=data?.results?.[0];const visualTop=Number(data?.primary_score??data?.visual_score??top?.visual_score??top?.score??0);const decision=Number(data?.decision_confidence??visualTop);const visualQuality=data?.visual_status??(visualTop>=92?"excellent":visualTop>=82?"good":visualTop>=70?"medium":"low");const statusLabel=visualQuality==="excellent"?"ALTA COMPATIBILIDADE VISUAL":visualQuality==="good"?"BOA COMPATIBILIDADE VISUAL":visualQuality==="medium"?"COMPATIBILIDADE MODERADA":"BAIXA COMPATIBILIDADE VISUAL";
  return <div className="identify-layout professional-identify">
    <div className="camera-card">
      <div className={`capture-area ${preview||scanning?"has-image":""}`} onClick={()=>!scanning&&input.current?.click()}>
        {scanning?<><video ref={videoRef} className="scanner-video" playsInline muted/><div className="scanner-overlay"><span className="scan-corners"></span><i className="scan-line"></i></div><div className="scanner-status"><ScanLine size={17}/><span>{scanStatus}</span><b>{scanCount} leitura(s)</b><div className="industrial-scan-metrics"><em>Cobertura <strong>{scanCoverage}%</strong></em><em>Diversidade <strong>{scanDiversity}%</strong></em><em>Cor estável <strong>{scanColorStability}%</strong></em></div></div></>:preview?<img src={preview}/>:<><div className="focus-box"><span></span></div><Camera size={42}/><h3>Fotografe a face da chapa</h3><p>Preencha o quadro com a textura, evite reflexos e sombras.</p></>}
      </div>
      <input ref={input} hidden type="file" accept="image/*" capture="environment" onChange={e=>e.target.files?.[0]&&identifyCamera(e.target.files[0])}/>
      <input ref={uploadInput} hidden type="file" accept="image/*" onChange={e=>e.target.files?.[0]&&identifyExisting(e.target.files[0])}/>
      <button className={`scan-button full ${scanning?"scanning":""}`} onClick={scanning?finalizeScannerSession:startScanner}>{scanning?<><CheckCircle2/> Finalizar scanner</>:<><ScanLine/> Scanear chapa inteira</>}</button>
      {scanning&&<button className="secondary full" onClick={stopScanner}><Square/> Cancelar varredura</button>}
      <button className="primary big full" onClick={()=>input.current?.click()}><Camera/> {preview?"Analisar outra foto":"Identificar por foto"}</button>
      <button className="secondary full" onClick={()=>uploadInput.current?.click()}><UploadCloud/> Escolher foto existente</button>
      <div className="capture-tip"><BrainCircuit/><span>V10 Motor Visual Industrial: a cor é validada antes da textura. Percorra centro, bordas e áreas com desenhos diferentes. O sistema cria fingerprints de várias regiões e exige consenso entre keyframes; uma coincidência isolada não define SKU. Finalize somente quando a cobertura estiver alta e a cor estiver estável.</span></div>
    </div>
    <div className="result-panel">{loading&&<div className="processing"><div className="spinner"></div><h3>Comparando referências...</h3><p>Foto física × catálogo Leo × fotos confirmadas.</p></div>}{!loading&&!data&&<div className="empty-result"><Camera size={34}/><h3>Possíveis produtos aparecerão aqui</h3><p>O sistema apresenta candidatos em ordem de similaridade para você confirmar.</p></div>}{!loading&&data?.error&&<div className="empty-result"><XCircle/><h3>Não foi possível analisar</h3><p>{data.error}</p></div>}{!loading&&data&&!data.error&&!top&&<div className="empty-result safe-no-match"><AlertTriangle/><h3>Nenhuma correspondência segura</h3><p>{data.rejection_reason||"A imagem não atingiu o nível mínimo de compatibilidade. Ajuste o enquadramento e tente novamente."}</p>{data.capture_quality&&<small>Qualidade da captura: {pct(data.capture_quality.quality)} • {data.capture_quality.message}</small>}</div>}
      {!loading&&top&&<><div className={`result-status visual-${visualQuality}`}>{visualQuality==="excellent"||visualQuality==="good"?<CheckCircle2/>:<AlertTriangle/>}<div><small>{statusLabel}</small><strong>{pct(visualTop)}</strong><em className="visual-match-note">Confiança para definir o SKU: {pct(decision)}</em></div>{data.catalog_assisted&&<span className="catalog-assisted"><Globe2 size={15}/> Catálogo Leo</span>}</div>
      <div className={`decision-trace ${String(data.decision_source||"").includes("ai")?"ai":"local"}`}><BrainCircuit size={16}/><div><strong>{data.decision_source==="visual_pattern_identified_sku_ambiguous"?"Padrão visual identificado — SKU exato depende da variação":data.decision_source==="ai_photometric_recovery"?"Recuperação multimodal por IA":data.decision_source==="ai_audited"?"Resultado auditado pela IA":data.decision_source==="ai_rejected"?"IA rejeitou os candidatos":String(data.decision_source||"").startsWith("manual_recovery")?"Conferência manual protegida":"Decisão do motor visual local"}</strong><small>{data.ai_audit?.used?(data.ai_audit?.outcome==="error"?`IA indisponível nesta leitura • ${data.ai_audit?.reason||"tempo limite"}`:`${data.ai_audit?.outcome==="select"?"Auditoria aprovada":"Auditoria concluída"} • ${data.ai_audit?.latency_ms||0} ms • confiança IA ${pct(data.ai_audit?.confidence||0)}`):"IA não necessária nesta identificação"}</small></div></div>
      {data.margin_insufficient&&<div className="inconclusive-banner"><AlertTriangle/><div><strong>SKU ainda não definido</strong><span>Os melhores candidatos estão próximos demais ({pct(data.score_margin)} de diferença; mínimo técnico {pct(data.min_margin_required)}). A imagem pode ser semelhante, mas o sistema não vai inventar certeza.</span></div></div>}
      {data.ambiguous&&<div className="ambiguity-banner"><Layers3/><div><strong>{data.ambiguity_count} variações com aparência praticamente igual</strong><span>{data.ambiguity_message}</span></div></div>}
      <div className="candidate-main"><button className="candidate-image zoomable" onClick={()=>top.image_url&&setZoom({url:`${API}${top.image_url}`,label:`SKU ${top.sku}`,description:top.description})}>{top.image_url?<img src={`${API}${top.image_url}`}/>:<Camera/>}</button><div className="candidate-main-copy"><small>{data.visual_equivalence_group?"PADRÃO VISUAL IDENTIFICADO — VARIAÇÃO A CONFIRMAR":!data.sku_defined?"CANDIDATO LÍDER — NÃO DEFINIDO":data.ambiguous?"CANDIDATO PRINCIPAL":"PRODUTO MAIS PROVÁVEL"}</small><strong>SKU {top.sku}</strong><p>{top.description}</p>{top.query_color_family&&<span className="color-gate-badge">Cor detectada: {top.query_color_family==="warm_wood"?"marrom / amadeirado":top.query_color_family==="neutral"?"neutro / cinza":"outra família"}</span>}{top.manufacturer&&<span>{top.manufacturer}</span>}</div></div>
      {data.sku_defined?<div className={`address-block professional-address ${missingAddress(top.address)?"missing":""}`}><div className="address-label"><MapPin/><span><small>LOCALIZAÇÃO OPERACIONAL DO SKU {top.sku}</small><em>Endereço vinculado à base operacional</em></span></div>{missingAddress(top.address)?<><strong>Localização não cadastrada</strong><p>O SKU foi identificado, mas ainda não possui endereço na base importada. Atualize a base operacional para vincular a localização correta.</p></>:<strong>{top.address}</strong>}</div>:<div className="address-block professional-address missing"><div className="address-label"><MapPin/><span><small>LOCALIZAÇÃO OPERACIONAL</small><em>Aguardando definição do SKU exato</em></span></div><strong>Localização ainda não liberada</strong><p>O padrão visual foi reconhecido, mas há variações visualmente equivalentes. Confirme espessura/faces para selecionar o SKU correto e então exibir o endereço.</p></div>}
      {!data.sku_defined&&<div className="manual-decision-note"><AlertTriangle/><span>Confirmação automática bloqueada. Revise as imagens/descrições ou faça o scanner da chapa inteira.</span></div>}{confirmed===top.sku?<div className="confirmed-banner"><CheckCircle2/><div><strong>Produto confirmado</strong><small>{data.learned?"Foto adicionada à inteligência deste SKU.":"Confirmação registrada."}</small></div></div>:<button className={data.sku_defined?"primary full":"secondary full"} onClick={()=>confirm(top.sku)}><CheckCircle2/> {data.sku_defined?"Confirmar este produto":"Confirmar manualmente este candidato"}</button>}{data.sku_defined&&<button className="secondary full" onClick={()=>print(top.sku)}><Printer/> Imprimir etiqueta</button>}{top.source_url&&<a className="source-button" href={top.source_url} target="_blank" rel="noreferrer"><ExternalLink/> Abrir produto no site Leo</a>}
      {data.results.length>1&&<div className="alternatives candidate-list"><h4>Outras relações possíveis</h4><p>Somente candidatos que passaram pelo filtro técnico de plausibilidade são exibidos. Em empate visual, confirme descrição, espessura e dimensão.</p>{data.results.slice(1).map((r:any)=><div className={`candidate-row ${confirmed===r.sku?"selected":""}`} key={r.sku}><button className="candidate-thumb zoomable" onClick={()=>r.image_url&&setZoom({url:`${API}${r.image_url}`,label:`SKU ${r.sku}`,description:r.description})}>{r.image_url?<img src={`${API}${r.image_url}`}/>:<Camera/>}</button><div className="candidate-info"><strong><span className="rank-badge">{r.rank}º</span> SKU {r.sku}</strong><small className="candidate-description">{r.description}</small><em>{r.media_source==="leo_site"?"Referência do site Leo":"Foto física confirmada"}</em></div><div className={`candidate-score ${scoreClass(r.visual_score??r.score)} ${Math.abs(r.score-top.score)<.35?"visual-tie":""}`}>{Math.abs(r.score-top.score)<.35?<><strong>Visual equivalente</strong><small>{pct(r.visual_score??r.score)} de semelhança</small></>:<>{pct(r.visual_score??r.score)}<small>compatibilidade visual</small></>}</div><button onClick={()=>confirm(r.sku)}>{confirmed===r.sku?"Confirmado":"Confirmar"}</button></div>)}</div>}</>}
    </div>{zoom&&<div className="image-modal-backdrop" onClick={()=>setZoom(undefined)}><div className="image-modal" onClick={e=>e.stopPropagation()}><button className="image-modal-close" onClick={()=>setZoom(undefined)}><X/></button><div className="image-modal-title"><strong>{zoom.label}</strong>{zoom.description&&<span>{zoom.description}</span>}</div><img src={zoom.url}/><small>Imagem ampliada para conferência visual</small></div></div>}
  </div>
}
