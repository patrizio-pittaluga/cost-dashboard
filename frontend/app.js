'use strict';
(() => {
const CATS=['Casa','Alimentari','Trasporti','Bollette','Salute','Svago','Shopping','Altro'];
const INCOME=['Stipendio','Extra','Rimborsi','Altre entrate'];
const DEFAULT_BUDGETS={Casa:700,Alimentari:400,Trasporti:180,Bollette:220,Salute:100,Svago:160,Shopping:140,Altro:100};
const $=id=>document.getElementById(id);
const html=s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const money=n=>new Intl.NumberFormat('it-IT',{style:'currency',currency:'EUR'}).format(Number(n)||0);
const usd=n=>new Intl.NumberFormat('it-IT',{style:'currency',currency:'USD'}).format(Number(n)||0);
const base64url=bytes=>btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
const localDay=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
const monthKey=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
const dateName=s=>new Date(s+'T12:00:00').toLocaleDateString('it-IT',{day:'2-digit',month:'short',year:'numeric'});
let config,token=null,state={transactions:[],budgets:{},recurring:[],planned:[]},favorites=[],calendarMonth=new Date(),calendarDate='',editPlanId=null,completePlanId=null,costs=null,month=new Date(),view='home',editId=null,editRecId=null,busy=false,me=null,activeSpace='',members=[];
const selectedSpace=()=>me?.spaces?.find(s=>s.id===activeSpace);
const canWrite=()=>!activeSpace||selectedSpace()?.role!=='viewer';
const scopedPath=path=>activeSpace&&/^\/(?:state|transactions|budgets|recurring|planned|favorites)(?:\/|$|\?)/.test(path)?path+(path.includes('?')?'&':'?')+'spaceId='+encodeURIComponent(activeSpace):path;
month.setDate(1);
function error(msg){$('errorBanner').textContent=msg;$('errorBanner').classList.remove('hidden');window.scrollTo({top:0,behavior:'smooth'});}
function clearError(){$('errorBanner').classList.add('hidden');}
function jwtExpired(jwt){try{const c=JSON.parse(atob(jwt.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));return c.exp*1000<=Date.now()+15000;}catch{return true;}}
const callbackUrl=()=>location.origin+'/';
async function login(){const verifier=base64url(crypto.getRandomValues(new Uint8Array(32)));const digest=new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier)));const nonce=base64url(crypto.getRandomValues(new Uint8Array(24)));sessionStorage.setItem('moneta-pkce',verifier);sessionStorage.setItem('moneta-state',nonce);const q=new URLSearchParams({response_type:'code',client_id:config.clientId,redirect_uri:callbackUrl(),scope:'openid email',state:nonce,code_challenge:base64url(digest),code_challenge_method:'S256'});location.assign(config.cognitoUrl+'/oauth2/authorize?'+q);}
async function handleCallback(){const q=new URLSearchParams(location.search);if(q.has('error'))throw Error('Cognito: '+(q.get('error_description')||q.get('error')));if(!q.has('code'))return;const verifier=sessionStorage.getItem('moneta-pkce');const saved=sessionStorage.getItem('moneta-state');sessionStorage.removeItem('moneta-pkce');sessionStorage.removeItem('moneta-state');const code=q.get('code');const valid=Boolean(verifier&&saved&&saved===q.get('state'));history.replaceState({},'',location.pathname);if(!valid)throw Error('Stato di autenticazione non valido.');const body=new URLSearchParams({grant_type:'authorization_code',client_id:config.clientId,code,code_verifier:verifier,redirect_uri:callbackUrl()});const r=await fetch(config.cognitoUrl+'/oauth2/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body});const data=await r.json();if(!r.ok||!data.access_token)throw Error('Login fallito: '+(data.error||r.status));token=data.access_token;sessionStorage.setItem('moneta-token',token);}
function logout(){sessionStorage.removeItem('moneta-token');token=null;location.assign(config.cognitoUrl+'/logout?'+new URLSearchParams({client_id:config.clientId,logout_uri:callbackUrl()}));}
async function api(path,method='GET',obj){if(!token||jwtExpired(token)){sessionStorage.removeItem('moneta-token');throw Error('Sessione scaduta. Effettua nuovamente il login.');}const r=await fetch(config.apiUrl+scopedPath(path),{method,headers:{Authorization:'Bearer '+token,...(obj===undefined?{}:{'Content-Type':'application/json'})},body:obj===undefined?undefined:JSON.stringify(obj),cache:'no-store'});if(r.status===204)return null;const data=await r.json().catch(()=>({}));if(!r.ok)throw Error(data.error||'Errore API '+r.status);return data;}
async function reload(){clearError();const scope=activeSpace;try{const [data,favs]=await Promise.all([api('/state'),api('/favorites')]);if(scope!==activeSpace)return;state={transactions:Array.isArray(data.transactions)?data.transactions:[],budgets:{...DEFAULT_BUDGETS,...data.budgets},recurring:Array.isArray(data.recurring)?data.recurring:[],planned:Array.isArray(data.planned)?data.planned:[]};favorites=Array.isArray(favs.favorites)?favs.favorites:[];render();}catch(e){error(e.message);}}
function navigate(target){if(target==='costs'&&!me?.isAdmin){error('Accesso ai costi AWS riservato agli amministratori');return;}view=target;document.querySelectorAll('.view').forEach(el=>el.classList.toggle('hidden',el.id!=='view-'+target));document.querySelectorAll('.nav-btn').forEach(el=>el.classList.toggle('active',el.dataset.view===target));$('topSection').textContent={home:'Panoramica',movements:'Movimenti',recurring:'Ricorrenze',costs:'Costi AWS',spaces:'Bilanci condivisi',settings:'Budget e dati',calendar:'Scadenze'}[target];window.scrollTo({top:0});if(target==='costs'&&costs)renderCosts();if(target==='spaces')renderSpaces();if(target==='calendar')renderCalendar();if($('mobileMoreMenu'))$('mobileMoreMenu').classList.add('hidden');document.querySelectorAll('[data-mobile-view]').forEach(el=>el.classList.toggle('active',el.dataset.mobileView===target));}
const sum=(list,type)=>list.filter(t=>t.type===type&&(activeSpace||t.affectsBalance!==false)).reduce((a,x)=>a+Math.round(Number(x.amount)*100),0)/100;
function balance(list){return Math.round(list.reduce((acc,t)=>acc+(t.affectsBalance===false?0:(t.type==='income'?1:-1)*Math.round(Number(t.amount)*100)),0))/100;}
const txSort=(a,b)=>b.date.localeCompare(a.date)||b.id.localeCompare(a.id);
function table(items,actions=false){if(!items.length)return '<div class="empty">Nessun movimento presente.</div>';return `<table class="data-table"><thead><tr><th>DESCRIZIONE</th><th>CATEGORIA</th><th>DATA</th><th class="right">IMPORTO</th>${actions?'<th class="right">AZIONI</th>':''}</tr></thead><tbody>${items.map(t=>`<tr><td><strong>${html(t.description)}</strong>${t.recurringId?'<div class="muted">↻ Ricorrente</div>':''}${t.linkedSpaceId?'<div class="muted">♧ Collegato a un bilancio condiviso'+(t.affectsBalance===false?' · nessun addebito personale':'')+'</div>':''}${activeSpace&&t.paymentSource==='personal'?'<div class="muted">Pagato con denaro personale</div>':''}</td><td><span class="pill">${html(t.category)}</span></td><td class="date-text">${html(dateName(t.date))}</td><td class="right ${t.type==='income'?'positive':'negative'}"><strong>${t.type==='income'?'+':'−'}${money(t.amount)}</strong></td>${actions?`<td class="right">${!t.readOnly&&canWrite()?`<button class="table-action" data-fav-tx="${html(t.id)}" title="Aggiungi ai preferiti">☆</button><button class="table-action" data-edit="${html(t.id)}">Modifica</button><button class="table-action danger" data-delete="${html(t.id)}">Elimina</button>`:'<span class="muted">Solo lettura</span>'}</td>`:''}</tr>`).join('')}</tbody></table>`;}
function chartSvg(series,labels,{colors=['#55e8bb'],currency='EUR',includeZero=false}={}){
 const W=670,H=245,L=58,R=20,T=20,B=42;
 const values=series.flatMap(s=>s);let max=Math.max(...values,0),min=Math.min(...values,0);
 if(includeZero){min=Math.min(0,min);max=Math.max(0,max);}if(max===min){max+=1;min-=1;}
 const padding=(max-min)*.12;max+=padding;min-=padding;
 const x=i=>L+(W-L-R)*(labels.length===1?.5:i/(labels.length-1));
 const y=n=>T+(H-T-B)*(max-n)/(max-min);
 const fmt=v=>currency==='USD'?usd(v):money(v);
 const grid=Array.from({length:4},(_,i)=>{const v=min+(max-min)*i/3,py=y(v);return `<line class="chart-gridline" x1="${L}" y1="${py.toFixed(1)}" x2="${W-R}" y2="${py.toFixed(1)}"/><text x="${L-8}" y="${(py+4).toFixed(1)}" text-anchor="end">${html(new Intl.NumberFormat('it-IT',{maximumFractionDigits:0,notation:Math.abs(v)>10000?'compact':'standard'}).format(v))}</text>`;}).join('');
 const paths=series.map((s,j)=>{const pts=s.map((v,i)=>`${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');const circles=s.map((v,i)=>`<circle cx="${x(i)}" cy="${y(v)}" r="3.4" fill="${colors[j%colors.length]}"><title>${html(labels[i])}: ${html(fmt(v))}</title></circle>`).join('');return `<polyline points="${pts}" fill="none" stroke="${colors[j%colors.length]}" stroke-width="3.0" stroke-linejoin="round" stroke-linecap="round"/>${circles}`;}).join('');
 return `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Grafico a linee"><g>${grid}<line class="chart-zero" x1="${L}" y1="${y(0)}" x2="${W-R}" y2="${y(0)}"/></g>${paths}${labels.map((name,i)=>`<text x="${x(i)}" y="${H-13}" text-anchor="middle">${html(name)}</text>`).join('')}</svg>`;
}
function render(){$('addButton').classList.toggle('hidden',!canWrite());$('addMovementButton').classList.toggle('hidden',!canWrite());$('addRecurringButton').classList.toggle('hidden',!canWrite());const today=localDay(),valid=state.transactions.filter(t=>t.date<=today),monthNow=today.slice(0,7),m=valid.filter(t=>t.date.startsWith(monthNow));$('totalBalance').textContent=money(balance(valid));$('totalMovements').textContent=`${valid.length} movimenti`;$('incomeTotal').textContent=money(sum(m,'income'));$('expenseTotal').textContent=money(sum(m,'expense'));$('balanceTotal').textContent=money(balance(m));$('incomeMonth').textContent=$('expenseMonth').textContent=new Date().toLocaleDateString('it-IT',{month:'long',year:'numeric'});$('recentRows').innerHTML=table([...state.transactions].sort(txSort).slice(0,7));
 const months=Array.from({length:6},(_,i)=>new Date(new Date().getFullYear(),new Date().getMonth()-5+i,1));const labels=months.map(d=>d.toLocaleDateString('it-IT',{month:'short'}));const inc=[],out=[],balances=[];
 months.forEach((d,i)=>{const key=monthKey(d),dateEnd=i===5?today:new Date(d.getFullYear(),d.getMonth()+1,0).toLocaleDateString('en-CA');const rows=valid.filter(t=>t.date.startsWith(key));inc.push(sum(rows,'income'));out.push(sum(rows,'expense'));const last=i===5?today:`${key}-${String(new Date(d.getFullYear(),d.getMonth()+1,0).getDate()).padStart(2,'0')}`;balances.push(balance(valid.filter(t=>t.date<=last)));});
 $('balanceChart').innerHTML=chartSvg([balances],labels,{colors:['#72e6d6']});$('flowChart').innerHTML=chartSvg([inc,out],labels,{colors:['#55e8bb','#ff8d9e'],includeZero:true});
 $('monthLabel').textContent=month.toLocaleDateString('it-IT',{month:'long',year:'numeric'});$('transactionRows').innerHTML=table(state.transactions.filter(t=>t.date.slice(0,7)===monthKey(month)).sort(txSort),true);
 $('recurringCount').textContent=state.recurring.length+' regole';$('recurringRows').innerHTML=recurringTable();renderBudgets();extraRender();}
function recurringTable(){const rows=[...state.recurring].sort((a,b)=>a.startDate.localeCompare(b.startDate));if(!rows.length)return '<div class="empty">Non hai ancora creato ricorrenze. Puoi iniziare con affitto, stipendi o abbonamenti.</div>';const freq={weekly:'settimanale',monthly:'mensile',quarterly:'trimestrale',yearly:'annuale'};return `<table class="data-table"><thead><tr><th>REGOLA</th><th>CADENZA</th><th>PROSSIMA/INIZIO</th><th class="right">IMPORTO</th><th class="right">AZIONI</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${html(r.description)}</strong><div class="muted">${r.active?'● Attiva':'○ In pausa'}</div></td><td><span class="pill">${r.interval>1?'ogni '+r.interval+' × ':''}${html(freq[r.frequency])}</span></td><td>${html(dateName(r.startDate))}</td><td class="right ${r.type==='income'?'positive':'negative'}">${r.type==='income'?'+':'−'}${money(r.amount)}</td><td class="right"><button class="table-action" ${canWrite()?'':'disabled'} data-rec-edit="${html(r.id)}">Modifica</button><button class="table-action danger" ${canWrite()?'':'disabled'} data-rec-delete="${html(r.id)}">Elimina</button></td></tr>`).join('')}</tbody></table>`;}
function renderBudgets(){const monthTx=state.transactions.filter(t=>t.date.slice(0,7)===monthKey(month));$('budgetRows').innerHTML=CATS.map(cat=>{const cap=Number(state.budgets[cat]||0),spent=sum(monthTx.filter(x=>x.category===cat),'expense'),p=cap?spent/cap*100:0;return `<div class="budget"><div class="budget-head"><strong>${html(cat)}</strong><input class="input budget-input" type="number" step="0.01" min="0" max="1000000" data-budget="${html(cat)}" aria-label="Budget ${html(cat)}" value="${cap}" ${canWrite()?'':'disabled'}></div><div class="track"><div class="fill ${p>100?'over':''}" style="width:${Math.min(100,Math.max(0,p))}%"></div></div><div class="muted">${money(spent)} di ${money(cap)}</div></div>`;}).join('');}
async function loadCosts(){clearError();$('costStatus').textContent='Caricamento costi AWS…';$('loadCostsButton').disabled=true;try{costs=await api('/costs');renderCosts();}catch(e){error(e.message);$('costStatus').textContent='Impossibile caricare i costi.';}finally{$('loadCostsButton').disabled=false;}}
function renderCosts(){if(!costs)return;$('awsBudget').textContent=usd(costs.budgetUSD||3);if(!costs.available){$('costStatus').textContent=costs.message||'Cost Explorer non disponibile.';return;}$('awsSpent').textContent=usd(costs.total);$('awsRemaining').textContent=usd((costs.budgetUSD||3)-costs.total);$('awsRemaining').classList.toggle('negative',costs.total>(costs.budgetUSD||3));$('awsCostUpdated').textContent='Aggiornato '+new Date(costs.updatedAt).toLocaleString('it-IT');const days=costs.daily||[];$('costChart').innerHTML=days.length?chartSvg([days.map(d=>d.amount)],days.map((d,i)=>i%Math.max(1,Math.ceil(days.length/8))===0?d.date.slice(-2):''),{colors:['#9fbbff'],currency:'USD',includeZero:true}):'<p class="empty">Ancora nessun costo registrato.</p>';$('costServices').innerHTML=(costs.services||[]).length?costs.services.map(s=>`<div class="service"><span>${html(s.name)}</span><strong>${usd(s.amount)}</strong></div>`).join(''):'<p class="empty">Nessun costo per servizio.</p>';$('costStatus').textContent=costs.scope;}
function categories(type,target){const selected=$(target).value;$(target).innerHTML=(type==='income'?INCOME:CATS).map(x=>`<option value="${html(x)}">${html(x)}</option>`).join('');if([...$(target).options].some(opt=>opt.value===selected))$(target).value=selected;}
function editTransaction(id=null){editId=id;const t=state.transactions.find(t=>t.id===id);$('txForm').reset();$('dialogTitle').textContent=t?'Modifica movimento':'Nuovo movimento';$('txType').value=t?.type||'expense';categories($('txType').value,'txCategory');$('txDescription').value=t?.description||'';$('txAmount').value=t?.amount??'';$('txDate').value=t?.date||localDay();$('txCategory').value=t?.category||($('txType').value==='income'?INCOME[0]:CATS[0]);$('txNote').value=t?.note||'';$('txFundingWrap').classList.toggle('hidden',!activeSpace);$('txFunding').value=t?.paymentSource||'fund';$('txDialog').showModal();}
function editRecurring(id=null){editRecId=id;const r=state.recurring.find(r=>r.id===id);$('recForm').reset();$('recDialogTitle').textContent=r?'Modifica ricorrenza':'Nuova ricorrenza';$('recType').value=r?.type||'expense';categories($('recType').value,'recCategory');$('recDescription').value=r?.description||'';$('recAmount').value=r?.amount??'';$('recStart').value=r?.startDate||localDay();$('recCategory').value=r?.category||CATS[0];$('recFrequency').value=r?.frequency||'monthly';$('recInterval').value=r?.interval??1;$('recEnd').value=r?.endDate||'';$('recNote').value=r?.note||'';$('recActive').checked=r?.active??true;$('recFundingWrap').classList.toggle('hidden',!activeSpace);$('recFunding').value=r?.paymentSource||'fund';$('recDialog').showModal();}
async function mutate(work){if(busy)return;busy=true;clearError();try{await work();await reload();}catch(e){error(e.message);}finally{busy=false;}}
function download(name,text,type){const url=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);}
function exportCsv(){const safe=s=>{const val=String(s??'');return '"'+(/^[\s]*[=+@-]/.test(val)?"'"+val:val).replace(/"/g,'""')+'"';};const rows=[['Data','Tipo','Descrizione','Categoria','Importo EUR','Note'],...state.transactions.map(t=>[t.date,t.type,t.description,t.category,t.amount,t.note])];download('moneta-movimenti.csv',rows.map(r=>r.map(safe).join(';')).join('\r\n'),'text/csv;charset=utf-8');}
async function refreshMe(){
 me=await api('/me');if(activeSpace&&!selectedSpace())activeSpace='';
 renderWorkspacePicker();
 document.querySelector('[data-view="costs"]').classList.toggle('hidden',!me.isAdmin);$('mobileMoreMenu').querySelector('[data-mobile-view="costs"]').classList.toggle('hidden',!me.isAdmin);
 if(!me.isAdmin&&view==='costs')navigate('home');
 renderSpaces();
}
function closeWorkspaceMenu(){ $('workspaceMenu').classList.add('hidden');$('workspaceToggle').setAttribute('aria-expanded','false'); }
function renderWorkspacePicker(){
 const selected=selectedSpace();$('workspaceLabel').textContent=selected?.name||'Il mio bilancio';$('workspaceIcon').textContent=selected?'⌂':'♙';
 const option=(id,name,subtitle,icon)=>`<button type="button" class="workspace-option ${activeSpace===id?'selected':''}" role="menuitemradio" aria-checked="${activeSpace===id}" data-pick-space="${html(id)}"><span class="workspace-option-icon">${icon}</span><span class="workspace-option-text"><strong>${html(name)}</strong><small>${html(subtitle)}</small></span>${activeSpace===id?'<span class="workspace-check">✓</span>':''}</button>`;
 $('workspaceOptions').innerHTML=option('','Il mio bilancio','Privato · Solo tu','♙')+(me?.spaces||[]).map(s=>option(s.id,s.name,s.role==='owner'?'Condiviso · Proprietario':s.role==='viewer'?'Condiviso · Lettura':'Condiviso · Membro','⌂')).join('');
}
async function selectWorkspace(value){closeWorkspaceMenu();activeSpace=value||'';renderWorkspacePicker();state={transactions:[],budgets:{},recurring:[],planned:[]};favorites=[];costs=null;await reload();if(view==='spaces')await renderSpaces();}
async function renderSpaces(){if(!me)return;
 $('spaceList').innerHTML=(me.spaces||[]).length?me.spaces.map(s=>`<div class="service"><span><strong>${html(s.name)}</strong><span class="muted"> · ${html(s.role)}</span></span><button class="btn btn-soft space-action" data-space="${html(s.id)}">Apri</button></div>`).join(''):'<div class="empty">Non hai ancora bilanci condivisi.</div>';
 $('inviteList').innerHTML=(me.invites||[]).length?me.invites.map(inv=>`<div class="service"><span><strong>${html(inv.spaceName)}</strong><span class="muted"> · ${html(inv.role)}</span></span><span><button class="btn btn-soft" data-accept="${html(inv.id)}">Accetta</button> <button class="btn btn-soft" data-decline="${html(inv.id)}">Rifiuta</button></span></div>`).join(''):'<div class="empty">Non ci sono inviti in attesa.</div>';
 $('spaceInviteForm').classList.add('hidden');$('membersList').innerHTML='';
 $('membershipHint').textContent=activeSpace?`Membri di ${selectedSpace()?.name||'bilancio'} · ${selectedSpace()?.role==='owner'?'Puoi invitare nuove persone':'Gestione riservata al proprietario'}`:'Apri prima un bilancio condiviso dal selettore in alto.';
 $('inviteOwnerNotice').classList.add('hidden');
 if(!activeSpace)return;
 try{const data=await api('/spaces/'+encodeURIComponent(activeSpace)+'/members');members=data.members||[];
  $('membersList').innerHTML=members.map(m=>`<div class="service"><span>${html(m.email||((m.id===me.userId)?"Tu":m.id.slice(0,8)+"…"))} <span class="muted">${html(m.role)}</span>${m.id===me.userId?' (tu)':''}</span>${selectedSpace()?.role==='owner'&&m.role!=='owner'?`<button class="btn btn-soft" data-remove="${html(m.id)}">Rimuovi</button>`:''}</div>`).join('');
  $('spaceInviteForm').classList.toggle('hidden',selectedSpace()?.role!=='owner');
  $('inviteOwnerNotice').classList.toggle('hidden',selectedSpace()?.role==='owner');
 }catch(e){error(e.message);}
}
// Moneta 2.1: preferences are stored in DynamoDB, not in browser localStorage.
const iso=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const daysBetween=(a,b)=>Math.floor((Date.UTC(b.getFullYear(),b.getMonth(),b.getDate())-Date.UTC(a.getFullYear(),a.getMonth(),a.getDate()))/86400000);
const monthAt=(start,n)=>{
 const y=start.getFullYear(),m=start.getMonth()+n,d=start.getDate();
 return new Date(y,m,Math.min(d,new Date(y,m+1,0).getDate()));
};
function recurringOccurrences(rule,from,to){
 if(!rule.active)return [];
 const start=new Date(rule.startDate+'T00:00:00');
 const end=rule.endDate||'';
 const count=Math.max(1,Number(rule.interval)||1);
 const width={monthly:1,quarterly:3,yearly:12}[rule.frequency];
 let index=0;
 if(rule.frequency==='weekly')index=Math.max(0,Math.floor(daysBetween(start,from)/(7*count))-1);
 else if(width)index=Math.max(0,Math.floor(((from.getFullYear()-start.getFullYear())*12+from.getMonth()-start.getMonth())/(width*count))-2);
 else return [];
 const out=[];
 for(let i=index;i<index+400;i++){
  const date=rule.frequency==='weekly'?new Date(start.getFullYear(),start.getMonth(),start.getDate()+i*7*count):monthAt(start,i*width*count);
  if(date>to)break;
  const day=iso(date);
  if(end&&day>end)break;
  if(date>=from&&date>=start)out.push({id:rule.id,date:day,type:rule.type,description:rule.description,category:rule.category,amount:rule.amount,kind:'recurring',status:state.transactions.some(t=>t.recurringId===rule.id&&t.date===day)?'completed':'scheduled'});
 }
 return out;
}
function timeline(from,to){
 const result=state.planned.filter(p=>p.dueDate>=iso(from)&&p.dueDate<=iso(to)).map(p=>({...p,date:p.dueDate,kind:'planned'}));
 for(const rule of state.recurring)result.push(...recurringOccurrences(rule,from,to));
 return result.sort((a,b)=>a.date.localeCompare(b.date)||a.description.localeCompare(b.description));
}
function stateLabel(item){return item.status==='completed'?'Registrata':item.date<localDay()?'Scaduta':item.kind==='recurring'?'Ricorrente':'Prevista';}
function eventRow(item,preview=false){
 const canManage=!preview&&item.kind==='planned'&&canWrite()&&item.status==='scheduled';
 const controls=canManage?`<div class="event-actions"><button type="button" class="btn btn-main btn-small" data-plan-complete="${html(item.id)}">Segna pagata</button><button type="button" class="table-action" data-plan-edit="${html(item.id)}">Modifica</button><button type="button" class="table-action danger" data-plan-delete="${html(item.id)}">Elimina</button></div>`:'';
 return `<div class="event-row"><div class="event-date"><strong>${html(new Date(item.date+'T12:00:00').toLocaleDateString('it-IT',{day:'2-digit'}))}</strong><small>${html(new Date(item.date+'T12:00:00').toLocaleDateString('it-IT',{month:'short'}))}</small></div><div class="event-info"><strong>${html(item.description)}</strong><span class="muted">${html(item.category)} · <span class="event-badge ${item.status==='completed'?'is-done':item.date<localDay()?'is-late':''}">${html(stateLabel(item))}</span></span>${controls}</div><strong class="event-value ${item.type==='income'?'positive':'negative'}">${item.type==='income'?'+':'−'}${money(item.amount)}</strong></div>`;
}
function renderFavorites(){
 const area=$('favoriteChips');
 if(!area)return;
 area.innerHTML=favorites.length?favorites.map(f=>`<div class="favorite-chip"><button type="button" data-use-fav="${html(f.id)}" title="Precompila un movimento">☆ ${html(f.description)} <span>${money(f.amount)}</span></button><button type="button" class="favorite-remove" data-delete-fav="${html(f.id)}" aria-label="Rimuovi ${html(f.description)} dai preferiti">×</button></div>`).join(''):'<p class="muted">Nessun preferito. Aggiungi un movimento abituale dal modulo rapido o dallo storico.</p>';
}
function renderUpcoming(){
 const now=new Date(localDay()+'T12:00:00'),from=new Date(now.getFullYear(),now.getMonth(),now.getDate()-7),to=new Date(now.getFullYear(),now.getMonth(),now.getDate()+30);
 const items=timeline(from,to).filter(i=>i.status==='scheduled'&&(i.date>=localDay()||i.kind==='planned')).slice(0,5);
 $('homeUpcoming').innerHTML=items.length?items.map(item=>eventRow(item,true)).join(''):'<div class="empty">Nessuna scadenza prevista nei prossimi 30 giorni.</div>';
}
function renderCalendar(){
 const from=new Date(calendarMonth.getFullYear(),calendarMonth.getMonth(),1);
 const to=new Date(calendarMonth.getFullYear(),calendarMonth.getMonth()+1,0);
 const items=timeline(from,to);
 $('calendarMonth').textContent=from.toLocaleDateString('it-IT',{month:'long',year:'numeric'});
 const day0=(from.getDay()+6)%7;
 const last=to.getDate();
 const byDate={};items.forEach(e=>{(byDate[e.date]??=[]).push(e);});
 const cells=[];
 for(let i=0;i<day0;i++)cells.push('<span class="calendar-cell blank" aria-hidden="true"></span>');
 for(let n=1;n<=last;n++){
  const key=iso(new Date(from.getFullYear(),from.getMonth(),n)),dayItems=byDate[key]||[];
  const hasPending=dayItems.some(i=>i.status==='scheduled');
  cells.push(`<button class="calendar-cell ${key===localDay()?'today':''} ${calendarDate===key?'selected':''}" type="button" data-calendar-day="${key}" aria-label="${html(dateName(key))}, ${dayItems.length} scadenze"><span class="day-number">${n}</span>${dayItems.length?`<span class="calendar-dot ${hasPending?'pending':'done'}"></span><small>${dayItems.length}</small>`:''}</button>`);
 }
 $('calendarGrid').innerHTML=cells.join('');
 const filtered=calendarDate&&calendarDate.startsWith(monthKey(from))?items.filter(i=>i.date===calendarDate):items;
 $('calendarList').innerHTML=filtered.length?filtered.map(eventRow).join(''):'<div class="empty">Nessuna scadenza in questo periodo.</div>';
}
function extraRender(){
 $('mobileDock').classList.remove('hidden');
 $('mobileDock').querySelectorAll('[data-mobile-view]').forEach(b=>b.classList.toggle('active',b.dataset.mobileView===view));
 renderFavorites();renderUpcoming();renderCalendar();
 $('addPlannedButton').classList.toggle('hidden',!canWrite());
}
function updateQuickCategories(){
 const type=document.querySelector('input[name="quickType"]:checked')?.value||'expense';categories(type,'quickCategory');
}
function openQuick(fav=null){
 if(!canWrite())return error('Accesso in sola lettura.');
 $('quickForm').reset();$('quickStatus').textContent='';
 document.querySelector(`input[name="quickType"][value="${fav?.type||'expense'}"]`).checked=true;
 updateQuickCategories();
 $('quickAmount').value=fav?.amount??'';
 $('quickDescription').value=fav?.description||'';
 $('quickCategory').value=fav?.category||((fav?.type==='income')?INCOME[0]:'Alimentari');
 $('quickDate').value=localDay();$('quickFundingWrap').classList.toggle('hidden',!activeSpace);
 $('quickFunding').value=fav?.paymentSource||'fund';
 $('quickDialog').showModal();
 setTimeout(()=>(fav?$('quickAmount'):$('quickAmount')).focus(),50);
}
function quickPayload(){
 const type=document.querySelector('input[name="quickType"]:checked')?.value||'expense';
 const amount=Number($('quickAmount').value);
 if(!Number.isFinite(amount)||amount<=0||amount>1000000)throw Error('Inserisci un importo valido.');
 const data={id:'tx-'+crypto.randomUUID(),type,amount,description:$('quickDescription').value.trim(),category:$('quickCategory').value,date:$('quickDate').value,note:''};
 if(!data.description)throw Error('Inserisci una descrizione.');
 if(activeSpace)data.paymentSource=$('quickFunding').value;
 return data;
}
async function saveQuick(keepOpen){
 if(busy)return;
 let tx;try{tx=quickPayload();}catch(err){$('quickStatus').textContent=err.message;return;}
 busy=true;clearError();$('quickStatus').textContent='Salvataggio in corso…';
 try{
  await api('/transactions','POST',tx);
  let favoriteError=false;
  if($('quickFavorite').checked){
   try{await api('/favorites','POST',{id:'fav-'+crypto.randomUUID(),type:tx.type,amount:tx.amount,description:tx.description,category:tx.category,paymentSource:tx.paymentSource||'fund',spaceId:activeSpace,note:''});}
   catch(e){favoriteError=true;}
  }
  await reload();
  if(keepOpen){$('quickAmount').value='';$('quickDescription').value='';$('quickFavorite').checked=false;$('quickAmount').focus();}
  else $('quickDialog').close();
  if(favoriteError)error('Movimento registrato, ma non è stato possibile salvare il preferito.');
  else if(keepOpen)$('quickStatus').textContent='✓ Salvato. Puoi aggiungere un altro movimento.';
 }catch(e){$('quickStatus').textContent='Errore: '+e.message;}
 finally{busy=false;}
}
function quickToFull(){
 let tx;try{tx=quickPayload();}catch(e){$('quickStatus').textContent=e.message;return;}
 $('quickDialog').close();editTransaction();
 $('txType').value=tx.type;categories(tx.type,'txCategory');$('txDescription').value=tx.description;
 $('txAmount').value=tx.amount;$('txDate').value=tx.date;$('txCategory').value=tx.category;
 if(activeSpace)$('txFunding').value=tx.paymentSource;
}
async function storeFavorite(tx){
 if(!canWrite())return error('Solo lettura');
 await mutate(async()=>{
  await api('/favorites','POST',{id:'fav-'+crypto.randomUUID(),type:tx.type,description:tx.description,
   category:tx.category,amount:tx.amount,note:tx.note||'',paymentSource:tx.paymentSource||'fund',spaceId:activeSpace});
 });
}
function openPlanned(id=null){
 if(!canWrite())return;
 const plan=state.planned.find(p=>p.id===id);
 if(id&&!plan)return;
 if(plan&&plan.status!=='scheduled')return error('Le scadenze registrate non sono modificabili.');
 editPlanId=id;
 $('plannedForm').reset();$('plannedTitle').textContent=plan?'Modifica scadenza':'Nuova scadenza';
 $('planType').value=plan?.type||'expense';categories($('planType').value,'planCategory');
 $('planDescription').value=plan?.description||'';$('planAmount').value=plan?.amount??'';
 $('planDate').value=plan?.dueDate||localDay();$('planCategory').value=plan?.category||(plan?.type==='income'?INCOME[0]:CATS[0]);
 $('planNote').value=plan?.note||'';$('planFundingWrap').classList.toggle('hidden',!activeSpace);
 $('planFunding').value=plan?.paymentSource||'fund';$('plannedDialog').showModal();
}
function planPayload(){
 const data={id:editPlanId||'p-'+crypto.randomUUID(),type:$('planType').value,description:$('planDescription').value.trim(),amount:Number($('planAmount').value),dueDate:$('planDate').value,category:$('planCategory').value,note:$('planNote').value.trim()};
 if(activeSpace)data.paymentSource=$('planFunding').value;
 return data;
}
function openComplete(id){
 const plan=state.planned.find(p=>p.id===id);
 if(!plan||plan.status!=='scheduled'||!canWrite())return;
 completePlanId=id;$('completeDate').value=localDay();
 $('completeSummary').textContent=`${plan.description} · ${money(plan.amount)} · Scadenza ${dateName(plan.dueDate)}`;
 $('completeDialog').showModal();
}
async function handleCalendarClick(e){
 const day=e.target.closest('[data-calendar-day]');
 if(day){calendarDate=calendarDate===day.dataset.calendarDay?'':day.dataset.calendarDay;renderCalendar();return;}
 const mark=e.target.closest('[data-plan-complete]');if(mark){openComplete(mark.dataset.planComplete);return;}
 const edit=e.target.closest('[data-plan-edit]');if(edit){openPlanned(edit.dataset.planEdit);return;}
 const del=e.target.closest('[data-plan-delete]');
 if(del&&confirm('Eliminare questa scadenza? Il saldo e i movimenti esistenti non cambieranno.'))await mutate(()=>api('/planned/'+encodeURIComponent(del.dataset.planDelete),'DELETE'));
}
function initPwa(){
 if(!('serviceWorker' in navigator)||!window.isSecureContext)return;
 window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js',{scope:'/'}).catch(()=>{}));
}

function bind(){
 $('openQuickButton').onclick=()=>openQuick();$('mobileQuick').onclick=()=>openQuick();
 $('closeQuick').onclick=()=>$('quickDialog').close();
 $('quickForm').onsubmit=e=>{e.preventDefault();saveQuick(false);};
 $('quickSaveMore').onclick=()=>{if($('quickForm').reportValidity())saveQuick(true);};
 $('quickDetails').onclick=quickToFull;
 document.querySelectorAll('input[name="quickType"]').forEach(r=>r.onchange=updateQuickCategories);
 $('favoriteChips').onclick=e=>{const f=e.target.closest('[data-use-fav]'),del=e.target.closest('[data-delete-fav]');
  if(f){const record=favorites.find(x=>x.id===f.dataset.useFav);if(record)openQuick(record);}
  if(del&&confirm('Rimuovere il preferito?'))mutate(()=>api('/favorites/'+encodeURIComponent(del.dataset.deleteFav),'DELETE'));
 };
 $('addPlannedButton').onclick=()=>openPlanned();
 $('calendarPrev').onclick=()=>{calendarMonth=new Date(calendarMonth.getFullYear(),calendarMonth.getMonth()-1,1);calendarDate='';renderCalendar();};
 $('calendarNext').onclick=()=>{calendarMonth=new Date(calendarMonth.getFullYear(),calendarMonth.getMonth()+1,1);calendarDate='';renderCalendar();};
 $('calendarGrid').onclick=handleCalendarClick;$('calendarList').onclick=handleCalendarClick;$('homeUpcoming').onclick=handleCalendarClick;
 $('closePlanned').onclick=$('cancelPlanned').onclick=()=>$('plannedDialog').close();
 $('planType').onchange=()=>categories($('planType').value,'planCategory');
 $('plannedForm').onsubmit=e=>{e.preventDefault();const payload=planPayload();mutate(async()=>{await api(editPlanId?'/planned/'+encodeURIComponent(editPlanId):'/planned',editPlanId?'PUT':'POST',payload);$('plannedDialog').close();});};
 $('closeComplete').onclick=$('cancelComplete').onclick=()=>$('completeDialog').close();
 $('completeForm').onsubmit=e=>{e.preventDefault();const id=completePlanId;mutate(async()=>{await api('/planned/'+encodeURIComponent(id)+'/complete','POST',{paidDate:$('completeDate').value});$('completeDialog').close();});};
 document.querySelectorAll('[data-mobile-view]').forEach(el=>el.onclick=()=>navigate(el.dataset.mobileView));
 $('mobileMore').onclick=()=>$('mobileMoreMenu').classList.toggle('hidden');$('mobileLogout').onclick=logout;
 document.querySelectorAll('[data-view]').forEach(el=>el.onclick=()=>navigate(el.dataset.view));document.querySelectorAll('[data-go]').forEach(el=>el.onclick=()=>navigate(el.dataset.go));$('loginButton').onclick=()=>login().catch(e=>$('loginMessage').textContent=e.message);$('logoutButton').onclick=logout;$('refreshButton').onclick=reload;$('addButton').onclick=$('addMovementButton').onclick=()=>editTransaction();$('addRecurringButton').onclick=()=>editRecurring();$('loadCostsButton').onclick=loadCosts;$('workspaceToggle').onclick=()=>{const menu=$('workspaceMenu');menu.classList.toggle('hidden');$('workspaceToggle').setAttribute('aria-expanded',String(!menu.classList.contains('hidden')));};
 $('workspaceOptions').onclick=e=>{const b=e.target.closest('[data-pick-space]');if(b)selectWorkspace(b.dataset.pickSpace);};
 $('manageSpacesShortcut').onclick=()=>{closeWorkspaceMenu();navigate('spaces');};
 document.addEventListener('click',e=>{if(!e.target.closest('#workspacePicker'))closeWorkspaceMenu();});
 document.addEventListener('keydown',e=>{if(e.key==='Escape')closeWorkspaceMenu();});$('prevMonth').onclick=()=>{month=new Date(month.getFullYear(),month.getMonth()-1,1);render();};$('nextMonth').onclick=()=>{month=new Date(month.getFullYear(),month.getMonth()+1,1);render();};$('txType').onchange=()=>categories($('txType').value,'txCategory');$('recType').onchange=()=>categories($('recType').value,'recCategory');$('cancelTx').onclick=$('cancelTxBottom').onclick=()=>$('txDialog').close();$('cancelRec').onclick=$('cancelRecBottom').onclick=()=>$('recDialog').close();
 $('txForm').onsubmit=e=>{e.preventDefault();const t={id:editId||'tx-'+crypto.randomUUID(),type:$('txType').value,description:$('txDescription').value.trim(),amount:Number($('txAmount').value),date:$('txDate').value,category:$('txCategory').value,note:$('txNote').value.trim()};if(activeSpace)t.paymentSource=$('txFunding').value;if(!Number.isFinite(t.amount)||t.amount<=0)return;mutate(async()=>{await api(editId?'/transactions/'+encodeURIComponent(editId):'/transactions',editId?'PUT':'POST',t);$('txDialog').close();});};
 $('recForm').onsubmit=e=>{e.preventDefault();const r={id:editRecId||'r-'+crypto.randomUUID(),type:$('recType').value,description:$('recDescription').value.trim(),amount:Number($('recAmount').value),startDate:$('recStart').value,category:$('recCategory').value,frequency:$('recFrequency').value,interval:Number($('recInterval').value),endDate:$('recEnd').value||null,note:$('recNote').value.trim(),active:$('recActive').checked};if(activeSpace)r.paymentSource=$('recFunding').value;if(!Number.isFinite(r.amount)||r.amount<=0)return;mutate(async()=>{await api(editRecId?'/recurring/'+encodeURIComponent(editRecId):'/recurring',editRecId?'PUT':'POST',r);$('recDialog').close();});};
 $('transactionRows').addEventListener('click',e=>{const a=e.target.closest('[data-edit]'),b=e.target.closest('[data-delete]'),f=e.target.closest('[data-fav-tx]');if(f){const tx=state.transactions.find(t=>t.id===f.dataset.favTx);if(tx)storeFavorite(tx);return;}if(a)editTransaction(a.dataset.edit);if(b&&confirm('Eliminare definitivamente questo movimento?'))mutate(()=>api('/transactions/'+encodeURIComponent(b.dataset.delete),'DELETE'));});
 $('recurringRows').addEventListener('click',e=>{const a=e.target.closest('[data-rec-edit]'),b=e.target.closest('[data-rec-delete]');if(a)editRecurring(a.dataset.recEdit);if(b&&confirm('Eliminare la ricorrenza? I movimenti già creati resteranno.'))mutate(()=>api('/recurring/'+encodeURIComponent(b.dataset.recDelete),'DELETE'));});
 $('budgetRows').addEventListener('change',e=>{const el=e.target.closest('[data-budget]');if(!el)return;const amount=Number(el.value);if(!Number.isFinite(amount)||amount<0||amount>1000000){error('Budget non valido');render();return;}mutate(()=>api('/budgets/'+encodeURIComponent(el.dataset.budget),'PUT',{amount}));});
 $('spaceCreateForm').onsubmit=e=>{e.preventDefault();mutate(async()=>{await api('/spaces','POST',{name:$('newSpaceName').value.trim()});$('newSpaceName').value='';await refreshMe();});};
 $('spaceInviteForm').onsubmit=e=>{e.preventDefault();mutate(async()=>{await api('/spaces/'+encodeURIComponent(activeSpace)+'/invites','POST',{email:$('inviteEmail').value.trim(),role:$('inviteRole').value});$('inviteEmail').value='';await refreshMe();});};
 $('spaceList').addEventListener('click',e=>{const b=e.target.closest('[data-space]');if(b){selectWorkspace(b.dataset.space);navigate('home');}});
 $('inviteList').addEventListener('click',e=>{const b=e.target.closest('[data-accept],[data-decline]');if(!b)return;const id=b.dataset.accept||b.dataset.decline;mutate(async()=>{await api('/invites/'+encodeURIComponent(id)+'/'+(b.dataset.accept?'accept':'decline'),'POST');await refreshMe();});});
 $('membersList').addEventListener('click',e=>{const b=e.target.closest('[data-remove]');if(!b||!confirm('Rimuovere questo membro dal bilancio?'))return;mutate(async()=>{await api('/spaces/'+encodeURIComponent(activeSpace)+'/members/'+encodeURIComponent(b.dataset.remove),'DELETE');await refreshMe();});});
 $('exportJson').onclick=()=>download('moneta-backup.json',JSON.stringify({...state,exportedAt:new Date().toISOString(),version:3},null,2),'application/json');$('exportCsv').onclick=exportCsv;
}
async function start(){bind();initPwa();try{const r=await fetch('/config.json',{cache:'no-store'});if(!r.ok)throw Error('config.json mancante: esegui deploy.sh.');config=await r.json();if(!config.apiUrl||!config.clientId||!config.cognitoUrl)throw Error('Configurazione AWS incompleta.');await handleCallback();token=token||sessionStorage.getItem('moneta-token');if(!token||jwtExpired(token)){sessionStorage.removeItem('moneta-token');return;}$('authView').classList.add('hidden');$('appView').classList.remove('hidden');await refreshMe();await reload();}catch(e){$('loginMessage').textContent=e.message;}}
start();
})();
