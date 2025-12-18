(function(){
  // Lightweight modal + drawing canvas for ControlNet scribble
  if (window.__controlCanvasInit) return; window.__controlCanvasInit = true;

  document.addEventListener('DOMContentLoaded', () => {
    const openBtn = document.getElementById('open-canvas-btn');
    if (!openBtn) return;

    function notify(type, message) {
      const text = (typeof message === 'string' && message) ? message : '';
      if (!text) return;
      try {
        if (window.UIToast && typeof window.UIToast[type] === 'function') {
          window.UIToast[type](text);
          return;
        }
      } catch (_) {}
      try { alert(text); } catch (_) {}
    }

    const root = document.createElement('div');
    root.id = 'control-canvas-overlay';
    root.style.cssText = 'position:fixed;inset:0;display:none;align-items:center;justify-content:center;z-index:9999;';
    root.innerHTML = `
      <div id="cc-card" style="width:min(960px, 96vw); max-height:92vh; background:#fff; border-radius:12px; box-shadow: var(--shadow-2xl); display:flex; flex-direction:column;">
        <div style="display:flex; align-items:center; justify-content:space-between; padding:10px 12px; border-bottom:1px solid var(--neutral-200);">
          <strong><i class="fas fa-pencil"></i> Scribble 캔버스</strong>
          <div style="display:flex; gap:8px; align-items:center;">
            <button id="cc-load-selected" class="chip-btn" title="선택된 컨트롤 불러오기">불러오기</button>
            <button id="cc-clear" class="chip-btn" title="초기화">초기화</button>
            <button id="cc-close" class="chip-btn" title="닫기">닫기</button>
          </div>
        </div>
        <div style="display:flex; gap:12px; padding:12px; align-items:flex-start; overflow:auto;">
          <div style="flex:1; min-width:0;">
            <div style="display:flex; gap:8px; align-items:center; margin-bottom:8px;">
              <label style="display:inline-flex; align-items:center; gap:6px;">도구
                <select id="cc-tool">
                  <option value="pen">연필</option>
                  <option value="eraser">지우개</option>
                </select>
              </label>
              <label style="display:inline-flex; align-items:center; gap:6px;">굵기
                <input id="cc-size" type="range" min="2" max="64" step="1" value="8" />
              </label>
              <label style="display:inline-flex; align-items:center; gap:6px;">색상
                <input id="cc-color" type="color" value="#000000" />
              </label>
            </div>
            <div style="position:relative; background:#ffffff; border:1px solid var(--neutral-200); border-radius:8px;">
              <canvas id="cc-canvas" width="800" height="800" style="width:100%; height:auto; display:block; background:#ffffff;"></canvas>
            </div>
          </div>
          <div style="width:220px; flex:none; display:flex; flex-direction:column; gap:8px;">
            <button id="cc-upload" class="chip-btn"><i class="fas fa-upload"></i> 서버에 저장</button>
            <small style="color:var(--neutral-600)">저장 시 "내 컨트롤" 탭에서 확인할 수 있습니다.</small>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(root);

    const overlay = root;
    const canvas = root.querySelector('#cc-canvas');
    const ctx = canvas.getContext('2d');
    const toolSel = root.querySelector('#cc-tool');
    const sizeSel = root.querySelector('#cc-size');
    const colorSel = root.querySelector('#cc-color');
    const btnClose = root.querySelector('#cc-close');
    const btnClear = root.querySelector('#cc-clear');
    const btnUpload = root.querySelector('#cc-upload');
    const btnLoadSelected = root.querySelector('#cc-load-selected');

    let drawing = false;
    let lastX = 0, lastY = 0;
    let dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));

    function resizeCanvasForDisplay(){
      const displayWidth = canvas.clientWidth;
      const displayHeight = Math.round(canvas.clientWidth);
      canvas.width = Math.round(displayWidth * dpr);
      canvas.height = Math.round(displayHeight * dpr);
      ctx.scale(dpr, dpr);
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0,0, canvas.width, canvas.height);
    }

    function open(){
        overlay.style.display = 'flex';
        overlay.style.opacity = '0';
        overlay.classList.add('fade-in');
        setTimeout(() => {
            overlay.style.opacity = '1';
            resizeCanvasForDisplay();
        }, 10);
    }
    function close(){
        overlay.classList.add('fade-out');
        setTimeout(() => {
            overlay.style.display = 'none';
            overlay.classList.remove('fade-in', 'fade-out');
        }, 300);
    }

    function getPos(e){
      if (e.touches && e.touches[0]) {
        const rect = canvas.getBoundingClientRect();
        return { x: e.touches[0].clientX - rect.left, y: e.touches[0].clientY - rect.top };
      }
      const rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }

    function strokeLine(x0,y0,x1,y1){
      const mode = toolSel.value;
      const lineWidth = Math.max(1, parseInt(sizeSel.value, 10) || 8);
      if (mode === 'eraser') {
        ctx.save();
        ctx.globalCompositeOperation = 'destination-out';
        ctx.strokeStyle = 'rgba(0,0,0,1)';
        ctx.lineWidth = lineWidth;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.beginPath();
        ctx.moveTo(x0,y0);
        ctx.lineTo(x1,y1);
        ctx.stroke();
        ctx.restore();
      } else {
        ctx.save();
        ctx.globalCompositeOperation = 'source-over';
        ctx.strokeStyle = colorSel.value || '#000000';
        ctx.lineWidth = lineWidth;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.beginPath();
        ctx.moveTo(x0,y0);
        ctx.lineTo(x1,y1);
        ctx.stroke();
        ctx.restore();
      }
    }

    function onDown(e){ drawing = true; const p = getPos(e); lastX=p.x; lastY=p.y; }
    function onMove(e){ if (!drawing) return; const p = getPos(e); strokeLine(lastX,lastY,p.x,p.y); lastX=p.x; lastY=p.y; }
    function onUp(){ drawing = false; }

    canvas.addEventListener('mousedown', onDown);
    canvas.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    canvas.addEventListener('touchstart', (e)=>{ e.preventDefault(); onDown(e); }, { passive:false });
    canvas.addEventListener('touchmove', (e)=>{ e.preventDefault(); onMove(e); }, { passive:false });
    canvas.addEventListener('touchend', (e)=>{ e.preventDefault(); onUp(e); }, { passive:false });

    function clearCanvas(){
      ctx.save();
      ctx.globalCompositeOperation = 'source-over';
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0,0, canvas.width, canvas.height);
      ctx.restore();
    }

    async function toPngBlob(){
      return await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
    }

    function getControlSlots(){
      try { const raw = localStorage.getItem('controlSlots'); const obj = raw ? JSON.parse(raw) : {}; return (obj && typeof obj==='object')?obj:{}; } catch(_) { return {}; }
    }
    function setControlSlots(obj){ try { localStorage.setItem('controlSlots', JSON.stringify(obj||{})); } catch(_) {}
    }
    function setControlSlot(slotName, imageId){ const slots = getControlSlots(); if (imageId) slots[slotName]=imageId; else delete slots[slotName]; setControlSlots(slots); }

    async function upload(){
      try {
        const blob = await toPngBlob();
        const fd = new FormData();
        fd.append('file', blob, 'scribble.png');
        const res = await fetch('/api/v1/controls/upload', { method: 'POST', body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '업로드 실패');
        try { setControlSlot('default', data.id); } catch(_) {}
        // Update floating slot immediately
        try {
          const floatingImg = document.getElementById('control-floating-img');
          const floatingEmpty = document.getElementById('control-floating-empty');
          const floatingClear = document.getElementById('control-clear');
          if (floatingImg) {
            floatingImg.style.display = 'block';
            floatingImg.src = '';
            floatingImg.src = data.url || '';
          }
          if (floatingEmpty) floatingEmpty.style.display = 'none';
          if (floatingClear) floatingClear.style.display = 'flex';
        } catch(_) {}
        // ControlNet 토글 자동 켜기
        const chk = document.getElementById('control-enabled');
        if (chk) chk.checked = true;
        // 갤러리 컨트롤 탭 갱신 유도: 저장 후 즉시 전환은 하지 않음
        notify('success', '컨트롤이 저장되었습니다. 내 컨트롤 탭에서 확인할 수 있어요.');
      } catch (e) {
        notify('error', '업로드 실패: ' + (e && e.message ? e.message : '오류'));
      }
    }

    async function loadSelectedToCanvas(){
      // Prefer new storage: controlSlots.default, fallback to legacy selectedControlId
      let id = '';
      try {
        const slotsRaw = localStorage.getItem('controlSlots');
        const slots = slotsRaw ? JSON.parse(slotsRaw) : {};
        if (slots && typeof slots === 'object' && typeof slots.default === 'string' && slots.default) {
          id = slots.default;
        }
      } catch (_) {}
      if (!id) {
        try { id = localStorage.getItem('selectedControlId') || ''; } catch(_) {}
      }
      if (!id) { notify('info', '선택된 컨트롤이 없습니다. 내 컨트롤 탭에서 선택하세요.'); return; }
      try {
        const res = await fetch('/api/v1/controls?page=1&size=500');
        const data = await res.json();
        const items = Array.isArray(data.items) ? data.items : [];
        const it = items.find(x => x.id === id);
        if (!it || !it.url) { notify('error', '컨트롤 이미지를 찾을 수 없습니다.'); return; }
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => {
          clearCanvas();
          // Fit image into canvas (keep aspect by cover)
          const cw = canvas.width / dpr, ch = canvas.height / dpr;
          const iw = img.width, ih = img.height;
          const cr = cw / ch; const ir = iw / ih;
          let dw, dh, dx, dy;
          if (ir > cr) { // image wider
            dh = ch; dw = ir * dh; dx = (cw - dw) / 2; dy = 0;
          } else {
            dw = cw; dh = dw / ir; dx = 0; dy = (ch - dh) / 2;
          }
          ctx.drawImage(img, dx, dy, dw, dh);
        };
        img.onerror = () => { notify('error', '이미지 로드 실패'); };
        img.src = it.url;
      } catch (_) {
        notify('error', '불러오기 실패');
      }
    }

    openBtn.addEventListener('click', open);
    btnClose.addEventListener('click', close);
    btnClear.addEventListener('click', clearCanvas);
    btnUpload.addEventListener('click', upload);
    btnLoadSelected.addEventListener('click', loadSelectedToCanvas);

    // Close on background click
    root.addEventListener('click', (e) => { if (e.target === root) close(); });
  });
})();


