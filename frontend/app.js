/* Dashboard privata: OAuth 2 Authorization Code + PKCE, nessuna password nel frontend.
 * Token di accesso soltanto nella sessione del browser (non in localStorage).
 * L'API valida firma, issuer, audience e token_use a ogni richiesta.
 */
'use strict';
(() => {
  const CATS = ['Casa','Alimentari','Trasporti','Bollette','Salute','Svago','Shopping','Altro'];
  const INCOME = ['Stipendio','Extra','Rimborsi','Altre entrate'];
  const DEFAULT_BUDGETS = { Casa:700, Alimentari:400, Trasporti:180, Bollette:220, Salute:100, Svago:160, Shopping:140, Altro:100 };
  const $ = id => document.getElementById(id);
  const money = n => new Intl.NumberFormat('it-IT',{style:'currency',currency:'EUR'}).format(Number(n)||0);
  const html = s => String(s??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
  const base64url = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  let config, token = null, state = { transactions:[], budgets:{} }, month = new Date(), editId = null, busy = false;
  month.setDate(1);
  const callbackUrl = () => location.origin + '/';
  function showError(message) { $('errorBanner').textContent = message; $('errorBanner').classList.remove('hidden'); }
  function clearError() { $('errorBanner').classList.add('hidden'); }
  function jwtExpired(jwt) {
    try { const part=jwt.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'); const claims=JSON.parse(atob(part)); return claims.exp*1000 <= Date.now()+15000; }
    catch { return true; }
  }
  async function login() {
    const bytes=crypto.getRandomValues(new Uint8Array(32));
    const verifier=base64url(bytes);
    const sha=new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier)));
    const stateValue=base64url(crypto.getRandomValues(new Uint8Array(24)));
    sessionStorage.setItem('bilancio-pkce', verifier);
    sessionStorage.setItem('bilancio-state', stateValue);
    const query=new URLSearchParams({response_type:'code',client_id:config.clientId,redirect_uri:callbackUrl(),scope:'openid email',state:stateValue,code_challenge:base64url(sha),code_challenge_method:'S256'});
    location.assign(config.cognitoUrl+'/oauth2/authorize?'+query);
  }
  async function processCallback() {
    const query=new URLSearchParams(location.search);
    if (query.has('error')) throw Error('Cognito: '+(query.get('error_description')||query.get('error')));
    if (!query.has('code')) return;
    const verifier=sessionStorage.getItem('bilancio-pkce');
    const savedState=sessionStorage.getItem('bilancio-state');
    const correct=Boolean(verifier && savedState && savedState===query.get('state'));
    sessionStorage.removeItem('bilancio-pkce');
    sessionStorage.removeItem('bilancio-state');
    history.replaceState({},'',location.pathname);
    if (!correct) throw Error('Risposta di autenticazione non valida (state/PKCE).');
    const body=new URLSearchParams({grant_type:'authorization_code',client_id:config.clientId,code:query.get('code'),code_verifier:verifier,redirect_uri:callbackUrl()});
    const res=await fetch(config.cognitoUrl+'/oauth2/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body});
    const data=await res.json();
    if(!res.ok || !data.access_token) throw Error('Impossibile completare l’accesso: '+(data.error||res.status));
    token=data.access_token;
    sessionStorage.setItem('bilancio-token',token);
  }
  function logout() {
    sessionStorage.removeItem('bilancio-token');
    token=null;
    location.assign(config.cognitoUrl+'/logout?'+new URLSearchParams({client_id:config.clientId,logout_uri:callbackUrl()}));
  }
  async function api(path,method='GET',data) {
    if(!token || jwtExpired(token)) { sessionStorage.removeItem('bilancio-token'); throw Error('Sessione scaduta. Esci e accedi di nuovo.'); }
    const response=await fetch(config.apiUrl+path,{method,headers:{Authorization:'Bearer '+token,...(data===undefined?{}:{'Content-Type':'application/json'})},body:data===undefined?undefined:JSON.stringify(data),cache:'no-store'});
    if(response.status===204) return null;
    const body=await response.json().catch(()=>({}));
    if(!response.ok) throw Error(body.error||('Errore API '+response.status));
    return body;
  }
  async function reload() {
    clearError();
    try {
      const value=await api('/state');
      state={transactions:Array.isArray(value.transactions)?value.transactions:[],budgets:{...DEFAULT_BUDGETS,...(value.budgets||{})}};
      render();
    } catch(e) { showError(e.message); }
  }
  const monthKey = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
  const txMonth = key => state.transactions.filter(t => t.date.slice(0,7)===key);
  const sum = (items,type) => items.filter(x=>x.type===type).reduce((a,t)=>a+Number(t.amount),0);
  function render() {
    const key=monthKey(month), items=txMonth(key), income=sum(items,'income'), expense=sum(items,'expense');
    $('monthLabel').textContent=month.toLocaleDateString('it-IT',{month:'long',year:'numeric'});
    $('incomeTotal').textContent=money(income);$('expenseTotal').textContent=money(expense);$('balanceTotal').textContent=money(income-expense);
    const data=[];
    for(let i=5;i>=0;i--){const d=new Date(month.getFullYear(),month.getMonth()-i,1);const m=txMonth(monthKey(d));data.push({name:d.toLocaleDateString('it-IT',{month:'short'}),inc:sum(m,'income'),exp:sum(m,'expense')});}
    const maximum=Math.max(1,...data.flatMap(d=>[d.inc,d.exp]));
    $('chart').innerHTML=data.map(d=>`<div class="chart-col"><div class="bars"><div class="bar exp" style="height:${Math.max(2,d.exp/maximum*125)}px" title="Uscite ${money(d.exp)}"></div><div class="bar inc" style="height:${Math.max(2,d.inc/maximum*125)}px" title="Entrate ${money(d.inc)}"></div></div><span>${html(d.name)}</span></div>`).join('');
    $('budgetRows').innerHTML=CATS.map(cat=>{const limit=Number(state.budgets[cat]||0),spent=sum(items.filter(t=>t.category===cat),'expense'),percent=limit?spent/limit*100:0;
      return `<div class="budget"><div class="budget-head"><label>${html(cat)}</label><input aria-label="Budget ${html(cat)}" class="input budget-input" type="number" min="0" max="100000000" step="0.01" data-budget="${html(cat)}" value="${limit}"></div><div class="track"><div class="fill ${percent>100?'over':''}" style="width:${Math.min(100,percent)}%"></div></div><div class="muted">${money(spent)} di ${money(limit)}</div></div>`;}).join('');
    const sorted=[...items].sort((a,b)=>b.date.localeCompare(a.date)||b.id.localeCompare(a.id));
    $('transactionRows').innerHTML=sorted.length?`<table class="table"><thead><tr><th>Data</th><th>Descrizione</th><th>Categoria</th><th class="right">Importo</th><th class="right">Azioni</th></tr></thead><tbody>${sorted.map(t=>`<tr><td>${html(t.date)}</td><td>${html(t.description)}</td><td>${html(t.category)}</td><td class="right" style="color:${t.type==='expense'?'var(--red)':'var(--green)'}">${t.type==='expense'?'-':'+'}${money(t.amount)}</td><td class="right"><button data-edit="${html(t.id)}">Modifica</button> <button data-delete="${html(t.id)}">Elimina</button></td></tr>`).join('')}</tbody></table>`:'<p class="empty">Nessun movimento per questo mese.</p>';
  }
  function updateCategories() {
    const type=$('txType').value,values=type==='expense'?CATS:INCOME;
    const selected=$('txCategory').value;
    $('txCategory').innerHTML=values.map(v=>`<option value="${html(v)}">${html(v)}</option>`).join('');
    if(values.includes(selected)) $('txCategory').value=selected;
  }
  function editTx(id=null) {
    editId=id;const t=state.transactions.find(x=>x.id===id);
    $('txForm').reset();$('dialogTitle').textContent=t?'Modifica movimento':'Nuovo movimento';
    $('txType').value=t?.type||'expense';updateCategories();
    $('txDescription').value=t?.description||'';$('txAmount').value=t?.amount??'';
    const today=new Date();const localDay=`${monthKey(today)}-${String(today.getDate()).padStart(2,'0')}`;
    $('txDate').value=t?.date||(monthKey(today)===monthKey(month)?localDay:monthKey(month)+'-01');
    $('txCategory').value=t?.category||($('txType').value==='expense'?CATS[0]:INCOME[0]);$('txNote').value=t?.note||'';
    $('txDialog').showModal();
  }
  async function runMutation(fn) {
    if(busy)return;busy=true;clearError();
    try { await fn();await reload(); } catch(e) { showError(e.message); }
    finally {busy=false;}
  }
  function download(name,text,mime) {
    const a=document.createElement('a'),url=URL.createObjectURL(new Blob([text],{type:mime}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);
  }
  function exportCsv() {
    const safe=s=>{const x=String(s??'');return '"'+(/^[\s]*[=+@-]/.test(x)?"'"+x:x).replace(/"/g,'""')+'"';};
    const rows=[['Data','Tipo','Descrizione','Categoria','Importo EUR','Note'],...state.transactions.map(t=>[t.date,t.type,t.description,t.category,t.amount,t.note])];
    download('bilancio-movimenti.csv',rows.map(r=>r.map(safe).join(';')).join('\r\n'),'text/csv;charset=utf-8');
  }
  function bind() {
    $('loginButton').onclick=()=>login().catch(e=>$('loginMessage').textContent=e.message);
    $('logoutButton').onclick=logout;
    $('refreshButton').onclick=reload;$('addButton').onclick=()=>editTx();
    $('prevMonth').onclick=()=>{month=new Date(month.getFullYear(),month.getMonth()-1,1);render();};
    $('nextMonth').onclick=()=>{month=new Date(month.getFullYear(),month.getMonth()+1,1);render();};
    $('txType').onchange=updateCategories;$('cancelTx').onclick=()=>$('txDialog').close();
    $('txForm').addEventListener('submit',e=>{e.preventDefault();const val={id:editId||'tx-'+crypto.randomUUID(),type:$('txType').value,description:$('txDescription').value.trim(),amount:Number($('txAmount').value),date:$('txDate').value,category:$('txCategory').value,note:$('txNote').value.trim()};
      if(!Number.isFinite(val.amount)||val.amount<=0||!val.description)return;
      runMutation(async()=>{await api(editId?'/transactions/'+encodeURIComponent(editId):'/transactions',editId?'PUT':'POST',val);$('txDialog').close();});});
    $('transactionRows').addEventListener('click',e=>{const a=e.target.closest('[data-edit]'),b=e.target.closest('[data-delete]');if(a)editTx(a.dataset.edit);if(b&&confirm('Eliminare questo movimento?'))runMutation(()=>api('/transactions/'+encodeURIComponent(b.dataset.delete),'DELETE'));});
    $('budgetRows').addEventListener('change',e=>{const el=e.target.closest('[data-budget]');if(!el)return;const amount=Number(el.value);if(!Number.isFinite(amount)||amount<0||amount>100000000){showError('Budget non valido');render();return;}runMutation(()=>api('/budgets/'+encodeURIComponent(el.dataset.budget),'PUT',{amount}));});
    $('exportJson').onclick=()=>download('bilancio-backup.json',JSON.stringify({...state,exportedAt:new Date().toISOString(),version:2},null,2),'application/json');
    $('exportCsv').onclick=exportCsv;
  }
  async function start() {
    bind();
    try {
      const res=await fetch('/config.json',{cache:'no-store'});
      if(!res.ok)throw Error('File config.json mancante; completare il deploy con scripts/deploy.sh.');
      config=await res.json();
      if(!config.apiUrl||!config.clientId||!config.cognitoUrl)throw Error('Configurazione AWS incompleta.');
      await processCallback();
      token=token||sessionStorage.getItem('bilancio-token');
      if(!token || jwtExpired(token)){sessionStorage.removeItem('bilancio-token');return;}
      $('authView').classList.add('hidden');$('appView').classList.remove('hidden');
      await reload();
    }catch(e){$('loginMessage').textContent=e.message;}
  }
  start();
})();
