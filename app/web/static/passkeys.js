(function(){
  'use strict';
  function b64urlToBytes(value){
    const pad='='.repeat((4-value.length%4)%4);
    const base64=(value+pad).replace(/-/g,'+').replace(/_/g,'/');
    const raw=atob(base64);
    const out=new Uint8Array(raw.length);
    for(let i=0;i<raw.length;i++) out[i]=raw.charCodeAt(i);
    return out;
  }
  function bytesToB64url(value){
    const bytes=new Uint8Array(value);
    let raw='';
    for(const b of bytes) raw+=String.fromCharCode(b);
    return btoa(raw).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  }
  function prepareCreation(options){
    const publicKey=Object.assign({},options);
    publicKey.challenge=b64urlToBytes(publicKey.challenge);
    if(publicKey.user && publicKey.user.id) publicKey.user=Object.assign({},publicKey.user,{id:b64urlToBytes(publicKey.user.id)});
    if(Array.isArray(publicKey.excludeCredentials)){
      publicKey.excludeCredentials=publicKey.excludeCredentials.map(c=>Object.assign({},c,{id:b64urlToBytes(c.id)}));
    }
    return publicKey;
  }
  function prepareRequest(options){
    const publicKey=Object.assign({},options);
    publicKey.challenge=b64urlToBytes(publicKey.challenge);
    if(Array.isArray(publicKey.allowCredentials)){
      publicKey.allowCredentials=publicKey.allowCredentials.map(c=>Object.assign({},c,{id:b64urlToBytes(c.id)}));
    }
    return publicKey;
  }
  function registrationJSON(credential){
    const response=credential.response;
    return {
      id: credential.id,
      rawId: bytesToB64url(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment || null,
      clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
      response: {
        attestationObject: bytesToB64url(response.attestationObject),
        clientDataJSON: bytesToB64url(response.clientDataJSON),
        transports: response.getTransports ? response.getTransports() : []
      }
    };
  }
  function authenticationJSON(credential){
    const response=credential.response;
    return {
      id: credential.id,
      rawId: bytesToB64url(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment || null,
      clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
      response: {
        authenticatorData: bytesToB64url(response.authenticatorData),
        clientDataJSON: bytesToB64url(response.clientDataJSON),
        signature: bytesToB64url(response.signature),
        userHandle: response.userHandle ? bytesToB64url(response.userHandle) : null
      }
    };
  }
  async function postForm(url, data){
    const body=new URLSearchParams();
    Object.entries(data).forEach(([k,v])=>body.set(k,String(v)));
    const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8','Accept':'application/json'},body});
    let payload={};
    try{payload=await response.json();}catch(_e){}
    if(!response.ok) throw new Error(payload.detail || ('HTTP '+response.status));
    return payload;
  }
  function errorText(error){
    if(error && error.name==='NotAllowedError') return 'Passkey не підтверджено або дію скасовано.';
    if(error && error.name==='InvalidStateError') return 'Цей passkey уже зареєстровано.';
    return (error && error.message) ? error.message : 'Не вдалося виконати операцію з passkey.';
  }
  function supported(){return !!(window.PublicKeyCredential && navigator.credentials);}

  document.addEventListener('DOMContentLoaded',function(){
    const login=document.querySelector('[data-passkey-login]');
    if(login){
      const button=login.querySelector('[data-passkey-auth]');
      const status=login.querySelector('[data-passkey-status]');
      const csrf=login.dataset.csrf || '';
      if(!supported()){
        if(status) status.textContent='Цей браузер не підтримує passkeys. Використайте Telegram-код.';
        if(button) button.disabled=true;
      }
      if(button) button.addEventListener('click',async function(){
        button.disabled=true;
        if(status) status.textContent='Очікуємо підтвердження на пристрої…';
        try{
          const options=await postForm('/admin/login/passkey/options',{_csrf:csrf});
          const credential=await navigator.credentials.get({publicKey:prepareRequest(options)});
          const result=await postForm('/admin/login/passkey/verify',{_csrf:csrf,credential_json:JSON.stringify(authenticationJSON(credential))});
          location.assign(result.redirect || '/admin/dashboard');
        }catch(error){
          if(status) status.textContent=errorText(error);
          button.disabled=false;
        }
      });
    }

    const enroll=document.querySelector('[data-passkey-enroll]');
    if(enroll){
      const button=enroll.querySelector('[data-passkey-create]');
      const status=enroll.querySelector('[data-passkey-status]');
      const label=enroll.querySelector('[data-passkey-label]');
      const password=enroll.querySelector('[data-passkey-password]');
      const csrf=enroll.dataset.csrf || '';
      if(!supported()){
        if(status) status.textContent='Цей браузер не підтримує WebAuthn/passkeys.';
        if(button) button.disabled=true;
      }
      if(button) button.addEventListener('click',async function(){
        button.disabled=true;
        if(status) status.textContent='Підтвердіть створення passkey на пристрої…';
        try{
          const options=await postForm('/admin/account/passkeys/options',{_csrf:csrf,current_password:(password && password.value) || ''});
          const credential=await navigator.credentials.create({publicKey:prepareCreation(options)});
          await postForm('/admin/account/passkeys/register',{
            _csrf:csrf,
            credential_json:JSON.stringify(registrationJSON(credential)),
            label:(label && label.value) || 'Passkey'
          });
          location.assign('/admin/account?tab=security');
        }catch(error){
          if(status) status.textContent=errorText(error);
          button.disabled=false;
        }
      });
    }
  });
})();
