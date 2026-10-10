/* AMP XP v1.20.3.1 — event attendance override and browser QR scanner. */
(function () {
  'use strict';
  const dialog=document.getElementById('attendanceOverrideDialog');
  const reason=document.getElementById('attendanceOverrideReason');
  const error=document.getElementById('attendanceOverrideError');
  const confirmButton=document.getElementById('attendanceOverrideConfirm');
  let pendingForm=null;
  if(dialog&&reason&&error&&confirmButton){
    document.addEventListener('submit',event=>{
      const form=event.target;
      if(!(form instanceof HTMLFormElement)||form.dataset.attendanceOverride!=='1'||form.dataset.overrideConfirmed==='1')return;
      event.preventDefault();pendingForm=form;reason.value='';error.hidden=true;dialog.showModal();requestAnimationFrame(()=>reason.focus({preventScroll:true}));
    },true);
    document.querySelectorAll('[data-override-cancel]').forEach(button=>button.addEventListener('click',()=>dialog.close()));
    confirmButton.addEventListener('click',()=>{const value=reason.value.trim();if(value.length<5){error.hidden=false;reason.focus();return;}if(!pendingForm){dialog.close();return;}const form=pendingForm;pendingForm=null;const input=form.querySelector('input[name="override_reason"]');if(input)input.value=value;form.dataset.overrideConfirmed='1';dialog.close();requestAnimationFrame(()=>form.requestSubmit());});
    dialog.addEventListener('close',()=>{pendingForm=null;error.hidden=true;});
  }

  const startBtn=document.getElementById('event-scanner-start');
  if(!startBtn)return;
  const stopBtn=document.getElementById('event-scanner-stop');
  const box=document.getElementById('event-scanner-box');
  const video=document.getElementById('event-scanner-video');
  const result=document.getElementById('event-scanner-result');
  const manual=document.getElementById('event-scanner-manual');
  const manualBtn=document.getElementById('event-scanner-manual-submit');
  const endpoint=startBtn.dataset.scannerEndpoint;
  const csrf=document.body.dataset.csrfToken||'';
  let stream=null,scanning=false,lastCode='',detector=null;

  function renderPerson(data){
    const person=document.createElement('div');person.className='scanner-person';
    const name=document.createElement('b');name.textContent=data.name||'Учасник';
    const code=document.createElement('code');code.textContent=data.amp_id||'';
    const registration=document.createElement('span');registration.textContent=data.registration||'Зареєстрований';
    person.append(name,code,registration);return person;
  }
  function renderResult(data){
    result.replaceChildren();
    if(!data.ok){result.className='scanner-result error';const text=document.createElement('b');text.textContent=data.error||'Помилка відмітки';result.append(text);return;}
    result.append(renderPerson(data));
    const message=document.createElement('p');const strong=document.createElement('b');strong.textContent=data.message||'';message.append(strong);if(data.xp)message.append(document.createTextNode(` • +${data.xp} XP`));result.append(message);
    if(data.state==='unregistered'){
      result.className='scanner-result warning';
      const button=document.createElement('button');button.type='button';button.className='primary';button.textContent='Зареєструвати та підтвердити';button.addEventListener('click',()=>submitCode(lastCode,'register_confirm'));result.append(button);return;
    }
    result.className='scanner-result success';
  }
  async function submitCode(code,action='scan'){
    code=(code||'').trim();if(!code||!endpoint)return;lastCode=code;result.className='scanner-result loading';result.textContent='Перевіряємо…';
    const form=new FormData();form.append('_csrf',csrf);form.append('code',code);form.append('action',action);
    try{const response=await fetch(endpoint,{method:'POST',body:form,credentials:'same-origin'});let data;try{data=await response.json();}catch(_err){data={ok:false,error:'Сервер повернув неочікувану відповідь.'};}renderResult(data);}catch(_err){renderResult({ok:false,error:'Не вдалося зв’язатися із сервером.'});}
  }
  async function stopScanner(){scanning=false;if(stream)stream.getTracks().forEach(track=>track.stop());stream=null;if(video)video.srcObject=null;if(box)box.hidden=true;startBtn.disabled=false;}
  async function scanLoop(){if(!scanning||!detector||!video)return;try{const codes=await detector.detect(video);if(codes&&codes.length&&codes[0].rawValue){const raw=codes[0].rawValue;await stopScanner();await submitCode(raw,'scan');return;}}catch(_err){}if(scanning)window.setTimeout(scanLoop,250);}
  startBtn.addEventListener('click',async()=>{if(result)result.textContent='';if(!navigator.mediaDevices?.getUserMedia){renderResult({ok:false,error:'Цей браузер не дозволяє відкрити камеру. Скористайтеся ручним полем нижче.'});return;}if(!('BarcodeDetector'in window)){renderResult({ok:false,error:'Камера QR у цьому браузері недоступна. Скористайтеся QR-сканером у Telegram або введіть АМП-код вручну.'});return;}try{detector=new BarcodeDetector({formats:['qr_code']});stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});video.srcObject=stream;await video.play();scanning=true;if(box)box.hidden=false;startBtn.disabled=true;scanLoop();}catch(_err){await stopScanner();renderResult({ok:false,error:'Не вдалося відкрити камеру. Перевірте дозвіл браузера або використайте ручне поле.'});}});
  stopBtn?.addEventListener('click',stopScanner);
  manualBtn?.addEventListener('click',()=>submitCode(manual?.value,'scan'));
  manual?.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();submitCode(manual.value,'scan');}});
  window.addEventListener('pagehide',stopScanner);
})();
