// Animación de ensamblado de piezas para optimización y generación de PDF
// API sencilla: const ctrl = OptimizerAnim.start('#optimizerAnimOverlay', 'opt'); ctrl.finish();
(function(){
  const OptimizerAnim = {};
  function rand(min,max){ return Math.random()*(max-min)+min; }
  function lerp(a,b,t){ return a+(b-a)*t; }
  // Paleta de grises (como el configurador 3D)
  const PALETTE = ['#cfd8dc','#b0bec5'];

  class BoardAnimation {
    constructor(canvas, mode){
      this.canvas = canvas; this.ctx = canvas.getContext('2d');
      this.mode = mode; // 'opt' | 'pdf'
      this.running = true; this.lastTs=null; this.elapsed=0;
      this.phase = 0; // para modo pdf
      this.cells = [];
      if(mode==='opt'){ this.setupPackedPieces(); }
      else { this.setupPdfPieces(); }
      requestAnimationFrame(this.loop.bind(this));
    }
    setupPackedPieces(){
      // Versión reducida: exactamente 7 piezas de distintos tamaños formando un rectángulo compacto
      const {width,height} = this.canvas;
      const margin = 16; const pad = 5; const areaW = width - margin*2; const areaH = height - margin*2;
      // Diseñar manualmente 7 tamaños proporcionales
      const baseSizes = [
        {w: areaW*0.32, h: areaH*0.35},
        {w: areaW*0.20, h: areaH*0.35},
        {w: areaW*0.28, h: areaH*0.25},
        {w: areaW*0.18, h: areaH*0.25},
        {w: areaW*0.22, h: areaH*0.30},
        {w: areaW*0.24, h: areaH*0.30},
        {w: areaW*0.16, h: areaH*0.30}
      ];
      // Ajustar ligeras variaciones para naturalidad
      baseSizes.forEach(s=>{ s.w *= rand(0.92,1.08); s.h *= rand(0.9,1.07); });
      // Packing simple: dos filas (4 arriba, 3 abajo)
      let yCursor = margin; let colorIdx=0;
      const rows = [baseSizes.slice(0,4), baseSizes.slice(4)];
      rows.forEach((row,i)=>{
        let xCursor = margin; const rowH = Math.max(...row.map(p=>p.h));
        row.forEach(p=>{
          const cx = xCursor + p.w/2; const cy = yCursor + rowH/2;
          this.cells.push({
            baseX: cx,
            baseY: cy,
            x: rand(0,width), y: rand(0,height),
            w: p.w, h: p.h,
            color: PALETTE[colorIdx % PALETTE.length],
            tEnter: rand(0,350)
          });
          colorIdx++; xCursor += p.w + pad;
        });
        yCursor += rowH + pad;
      });
      // Shuffle inicial para animación de ordenamiento
      this.shuffleTimer = 0;
    }
    shufflePacked(){
      // Reordenar solo intercambio de posiciones destino entre piezas
      const indices = [...this.cells.keys()];
      for(let i=indices.length-1;i>0;i--){ const j = Math.floor(Math.random()*(i+1)); [indices[i],indices[j]]=[indices[j],indices[i]]; }
      const dest = indices.map(i=>({x:this.cells[i].baseX,y:this.cells[i].baseY}));
      this.cells.forEach((c,i)=>{ c.baseX = dest[i].x; c.baseY = dest[i].y; });
    }
    setupPdfPieces(){
      // Reutilizar antigua lógica simplificada para transición a icono PDF
      const {width,height} = this.canvas;
      const count = 28;
      this.cells = [];
      for(let i=0;i<count;i++){
        const w = rand(24,70); const h = rand(22,60);
        this.cells.push({
          x: rand(width*0.1,width*0.9), y: rand(height*0.2,height*0.8),
          w, h, tx:0, ty:0, color: 'rgba(255,255,255,0.25)'
        });
      }
      // pack objetivo
      let cx=0, cy=0, rowH=0; const pad=3; const maxW = width*0.65;
      this.cells.forEach(p=>{
        if(cx + p.w > maxW){ cx=0; cy += rowH + pad; rowH=0; }
        p.tx = width*0.18 + cx; p.ty = height*0.15 + cy;
        cx += p.w + pad; rowH = Math.max(rowH,p.h);
      });
      this.totalPackedHeight = cy + rowH;
    }
    loop(ts){
      if(!this.running) return;
      if(!this.lastTs) this.lastTs = ts;
      const dt = ts - this.lastTs; this.lastTs = ts;
      this.elapsed += dt;
      if(this.mode==='opt'){
        this.shuffleTimer += dt;
        // cada 1800ms reordenar
        if(this.shuffleTimer > 1600){ this.shufflePacked(); this.shuffleTimer = 0; }
      } else {
        // fases para pdf
        const phaseDur = {0:1200,1:1200,2:700}[this.phase] || 1000;
        if(this.elapsed > phaseDur){ this.phase++; this.elapsed = 0; if(this.phase>2) this.phase=3; }
      }
      this.draw(dt);
      requestAnimationFrame(this.loop.bind(this));
    }
    draw(dt){
      const ctx = this.ctx; const {width,height} = this.canvas;
      ctx.clearRect(0,0,width,height);
      if(this.mode==='opt'){
        // Borde con pulso alpha
        const pulse = (Math.sin(this.elapsed/600)+1)/2; // 0..1
        ctx.strokeStyle=`rgba(255,255,255,${0.40 + pulse*0.25})`; ctx.lineWidth=2; ctx.strokeRect(6,6,width-12,height-12);
        this.cells.forEach(c=>{
          const tIn = Math.min(1, (this.elapsed - c.tEnter)/650);
          const eased = tIn<0?0:(tIn*tIn*(3-2*tIn));
          // interpolación suave hacia destino actual
          c.x = lerp(c.x, c.baseX, 0.10);
          c.y = lerp(c.y, c.baseY, 0.10);
          const scale = eased*0.95 + 0.05;
          ctx.save(); ctx.translate(c.x, c.y); ctx.scale(scale, scale);
          ctx.fillStyle = c.color; ctx.globalAlpha = 0.85 + pulse*0.10;
          ctx.beginPath(); ctx.rect(-c.w/2,-c.h/2,c.w,c.h); ctx.fill();
          // borde sutil
          ctx.strokeStyle='rgba(255,255,255,0.55)'; ctx.lineWidth=1.1; ctx.stroke();
          ctx.restore();
        });
      } else {
        // modo pdf original simplificado
        this.cells.forEach(p=>{
          let cx, cy, cw, ch;
          if(this.phase===0){ // entrada
            cx = p.x; cy = p.y; cw = p.w; ch=p.h;
          }else if(this.phase===1){ // pack
            cx = lerp(p.x, p.tx, this.elapsed/1100); cy = lerp(p.y, p.ty, this.elapsed/1100); cw=p.w; ch=p.h;
          }else if(this.phase===2){ // morph a página
            const pageW = width*0.55; const pageH = this.totalPackedHeight+40; const baseX = width*0.5; const baseY = height*0.5;
            cx = lerp(p.tx, baseX, this.elapsed/650); cy = lerp(p.ty, baseY, this.elapsed/650);
            cw = lerp(p.w, pageW, this.elapsed/650); ch = lerp(p.h, pageH, this.elapsed/650);
          }else{ // icono final
            cx = width*0.5; cy = height*0.5; cw = width*0.55; ch = this.totalPackedHeight+40;
          }
          ctx.save(); ctx.translate(cx, cy);
          ctx.fillStyle = p.color; ctx.globalAlpha = 0.8;
          ctx.beginPath(); ctx.rect(-cw/2,-ch/2,cw,ch); ctx.fill(); ctx.restore();
        });
        if(this.phase>=3){
          ctx.save(); ctx.translate(width*0.5,height*0.5);
            ctx.strokeStyle='rgba(255,255,255,0.8)'; ctx.lineWidth=3;
            ctx.strokeRect(-width*0.55/2,-(this.totalPackedHeight+40)/2,width*0.55,this.totalPackedHeight+40);
            ctx.fillStyle='rgba(255,255,255,0.85)'; ctx.font='bold 30px system-ui'; ctx.textAlign='center'; ctx.textBaseline='middle'; ctx.fillText('PDF',0,0);
          ctx.restore();
        }
      }
    }
    finish(){ this.running=false; }
  }

  OptimizerAnim.start = function(selector, mode){
    const el = typeof selector==='string'? document.querySelector(selector): selector;
    if(!el) return { finish:()=>{} };
    el.classList.add('oa-visible');
    // insertar etiqueta si no existe
    if(!el.querySelector('.oa-label')){
      const lbl = document.createElement('div'); lbl.className='oa-label'; lbl.textContent = (mode==='opt'? 'Optimizando…':'Generando PDF…'); el.appendChild(lbl);
    } else {
      el.querySelector('.oa-label').textContent = (mode==='opt'? 'Optimizando…':'Generando PDF…');
    }
    const canvas = el.querySelector('canvas'); if(!canvas){ return { finish:()=> el.classList.remove('oa-visible') }; }
    canvas.width = 320; canvas.height = 220;
    const anim = new BoardAnimation(canvas, mode);
    return { finish: ()=>{ anim.finish(); el.classList.remove('oa-visible'); } };
  };
  window.OptimizerAnim = OptimizerAnim;
})();
