'use strict';
const $=s=>document.querySelector(s), audio=$('#audio');
let songs=[],selected=null,queue=[],playing=null,playToken=0;
const escapeHTML=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=d=>d?new Date(d+'T12:00:00Z').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}):'Not verified';
const compactDate=d=>d?Number(d.slice(5,7))+'.'+Number(d.slice(8,10))+'.'+d.slice(2,4):'—';
const normalizeSearch=s=>s.toLowerCase().replace(/[^a-z0-9]/g,'');
const tracksFor=p=>p?.tracks?.length?p.tracks:p?.audio?[{url:p.audio,title:p.track||'',duration:p.duration}]:[];
const playable=p=>tracksFor(p).length>0;
const labels={first:'First documented',last:'Last documented',best:'HeadyVersion community favorite'};
function icon(name){return `<svg class="ui-icon" aria-hidden="true" focusable="false"><use href="#sketch-${name}"></use></svg>`}
const method=$('#method'),homescreen=$('#homescreen'),dialogs=[method,homescreen];let activeDialog=method,methodOpener=null,methodScroll=0,methodFallback=false;
function openMethod(opener,dlg=method){if(dialogs.some(d=>d.open))return;activeDialog=dlg;methodOpener=opener instanceof HTMLElement?opener:document.activeElement;methodScroll=window.scrollY;methodFallback=typeof dlg.showModal!=='function';if(methodFallback){dlg.setAttribute('open','');dlg.setAttribute('aria-modal','true');$('#method-backdrop').hidden=false;document.querySelectorAll('body > header, body > main, body > .player').forEach(el=>el.inert=true)}else dlg.showModal();document.body.style.top=`-${methodScroll}px`;document.body.classList.add('method-open');dlg.querySelector('.method-body').scrollTop=0;dlg.querySelector('h2').focus({preventScroll:true})}
function restoreMethod(){document.body.classList.remove('method-open');document.body.style.top='';$('#method-backdrop').hidden=true;document.querySelectorAll('body > header, body > main, body > .player').forEach(el=>el.inert=false);window.scrollTo(0,methodScroll);methodOpener?.focus({preventScroll:true})}
function closeMethod(){const dlg=activeDialog;if(!dlg.open)return;if(methodFallback){dlg.removeAttribute('open');dlg.removeAttribute('aria-modal');restoreMethod()}else {dlg.close();restoreMethod()}}
dialogs.forEach(dlg=>{dlg.addEventListener('cancel',e=>{e.preventDefault();closeMethod()});dlg.querySelector('.close').addEventListener('click',closeMethod)});
document.addEventListener('click',e=>{const trigger=e.target.closest('[data-open-method]');if(trigger){e.preventDefault();openMethod(trigger);return}const hs=e.target.closest('[data-open-homescreen]');if(hs){e.preventDefault();openMethod(hs,homescreen)}});
dialogs.forEach(dlg=>dlg.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();closeMethod()}if(e.key==='Tab'){const focusable=[...dlg.querySelectorAll('button,a[href],select,input,[tabindex="0"]')];const first=focusable[0],last=focusable.at(-1),title=dlg.querySelector('h2');if(e.shiftKey&&(document.activeElement===first||document.activeElement===title)){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}}));
function filtered(){const q=$('#search').value.toLowerCase().replace(/[^a-z0-9]/g,'');return songs.filter(s=>[s.name,...(s.aliases||[])].some(n=>normalizeSearch(n).includes(q))).sort((a,b)=>{const mode=$('#sort').value;if(mode==='rank')return (a.rank??Infinity)-(b.rank??Infinity)||a.name.localeCompare(b.name);if(mode==='live')return (a.liveRank??Infinity)-(b.liveRank??Infinity)||a.name.localeCompare(b.name);if(mode==='first')return (a.first?.date||'9999').localeCompare(b.first?.date||'9999')||a.name.localeCompare(b.name);return a.name.localeCompare(b.name)})}
function renderList(){const list=filtered();$('#rank-note').hidden=$('#sort').value!=='rank';$('#live-note').hidden=$('#sort').value!=='live';$('#count').textContent=`${list.length} of ${songs.length} songs`;$('#songs').innerHTML=list.length?list.map(s=>`<button class="song-button ${s.kind==='sequence'?'sequence':''} ${selected===s?'active':''}" data-song="${escapeHTML(s.name)}" ${selected===s?'aria-current="true"':''}><span class="num">${$('#sort').value==='rank'?(s.rank?'#'+s.rank:'—'):$('#sort').value==='live'?(s.liveRank?'#'+s.liveRank:'—'):String(list.indexOf(s)+1).padStart(2,'0')}</span><span class="song-name">${escapeHTML(s.name)}${s.kind==='sequence'?'<small class="sequence-tag">Live sequence</small>':''}${$('#sort').value==='live'?'<small class="live-count">'+(s.liveRank?(s.liveApproximate?'~':'')+s.liveCount+' live plays':'No count supplied')+'</small>':''}${$('#sort').value==='first'?'<small class="live-count">'+(s.first?.date?'Debut '+compactDate(s.first.date):'No verified date')+'</small>':''}</span>${selected===s?'<span class="arrow">'+icon('next')+'</span>':''}</button>`).join(''):`<p class="empty">No match for “${escapeHTML($('#search').value.trim())}”. This collection is around 100 of the songs fans love most, and more can be added. <a class="request-link" href="${escapeHTML(requestHref($('#search').value.trim()))}">Request it</a></p>`;$('#songs').querySelectorAll('button').forEach(b=>b.onclick=()=>{selectSong(b.dataset.song);if(matchMedia('(max-width:650px)').matches)$('#detail').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth',block:'start'})})}
function tapeVariation(s,i){const seed=Array.from(s.name).reduce((n,c)=>(n*31+c.charCodeAt(0))>>>0,0);return {paper:(seed+i)%4,icon:i}}
function card(s,k,i){const variation=tapeVariation(s,i);const p=s[k];const hasAudio=playable(p);const location=p?.venue?.split(' - ')||[];const venue=p?.venueName||location[0]||'No verified selection';const city=p?.city||location.slice(1).join(' · ');let note=k==='best'?(p?.sourceType==='headyversion'?`${p.votes} HeadyVersion votes · Checked ${date(p.checkedAt)}. ${p.ties?.length?'Tied for the top vote with '+p.ties.map(t=>date(t.date)).join(', ')+'. Displaying the first entry listed.':(s.kind==='sequence'?'Highest-voted complete sequence.':'Highest-voted entry in this song category.')}`:'Best not yet verified.'):(p?.note||'Earliest concert listing in source; early histories may be incomplete.');if(k==='last')note=p?.note||'Last concert listing with the original Grateful Dead.';if(s.kind==='sequence'&&k==='first')note=p?.note||'First documented complete sequence.';if(s.researchPending&&k!=='best')note='Performance details and recordings have not been verified yet.';if(p?.combined&&s.kind!=='sequence'&&/>\s*\S/.test(p.track))note+=' This track includes both songs: '+p.track.replace(/\s*-*>+\s*/g,' > ')+'.';if(s.kind==='sequence'&&hasAudio)note+=` Plays the full sequence · ${p.tracks.length} recording ${p.tracks.length===1?'track':'tracks'}.`;if(p?.date&&!hasAudio)note+=' No complete matched tape found for this date.';
if(k==='best'&&p?.sequence)note+=' Votes here are for the individual-song category; the sequence has a separate ranking.';
return `<article class="tape ${k} paper-${variation.paper}"><div class="tape-band"><span class="tape-band-title"><b>${['The First','The Last','The Best'][i]}</b><span aria-hidden="true"> - </span>${escapeHTML(s.short||s.name)}</span></div><div class="cassette-spine"><div class="spine-paper"><div class="spine-writing"><h3 class="venue" title="${escapeHTML(venue)}"><time datetime="${p?.date||''}" title="${date(p?.date)}">${p?.date?compactDate(p.date):'?.?.??'}</time><span aria-hidden="true"> - </span>${escapeHTML(venue)}</h3></div><span class="spine-icon icon-${variation.icon}" role="img" aria-label="Grateful Dead ${['rose','skull','lightning bolt'][variation.icon]} sketch"></span></div></div>${city?`<p class="city">${escapeHTML(city)}</p>`:''}<p class="tape-note">${escapeHTML(note)}</p><button data-play="${k}" ${hasAudio?'':'disabled'} aria-label="${hasAudio?'Play':'Audio unavailable for'} ${labels[k]} ${escapeHTML(s.name)}">${hasAudio?icon('play')+(s.kind==='sequence'?' Play sequence':' Play tape'):!p?.date?'Not yet verified':s.researchPending&&k!=='best'?'Research pending':'No matched tape'}</button><div class="source-links">${k==='best'&&p?.sequence?`<a href="${escapeHTML(p.sequence.source)}" target="_blank" rel="noopener">Sequence ranking ${icon('external')}</a>`:''}${p?.source?`<a${k==='best'?' class="vote-link"':''} href="${escapeHTML(p.source)}" target="_blank" rel="noopener">${k==='best'?'Not your favorite? Vote at HeadyVersion':p.sourceLabel||'Setlist'} ${icon('external')}</a>`:''}${p?.additionalSource?`<a href="${escapeHTML(p.additionalSource)}" target="_blank" rel="noopener">Date dispute ${icon('external')}</a>`:''}${p?.recording?`<a href="${escapeHTML(p.recording)}" target="_blank" rel="noopener">Recording ${icon('external')}</a>`:p?.archiveSearch?`<a href="${escapeHTML(p.archiveSearch)}" target="_blank" rel="noopener">Search tapes ${icon('external')}</a>`:''}</div></article>`}
const requestHref=q=>{const to=['mountaineerbob','gmail.com'].join('@');const body=`Song I'd like added: ${q||''}\n\nWhy it belongs (optional):\n`;return 'mailto:'+to+'?subject='+encodeURIComponent('Song request for First Last Best'+(q?': '+q:''))+'&body='+encodeURIComponent(body)};
$('#request-song').href=requestHref('');$('#request-song-modal').href=requestHref('');
const reportHref=name=>{const to=['mountaineerbob','gmail.com'].join('@');const body=`Song: ${name}\nPage: https://firstlastbest.com/#${encodeURIComponent(name)}\n\nWhich card (The First, The Last, or The Best)?\n\nWhat's wrong, and what should it say?\n\nA link to a source, if you have one:\n`;return 'mailto:'+to+'?subject='+encodeURIComponent('Mistake on First Last Best: '+name)+'&body='+encodeURIComponent(body)};
function selectSong(name,updateURL=true){const s=songs.find(s=>s.name===name);if(!s)return false;selected=s;renderList();const available=['first','last','best'].filter(k=>playable(s[k]));$('#detail').innerHTML=`<div class="song-top"><div><p class="song-kicker">THE GRATEFUL DEAD SONGBOOK</p><h2>${escapeHTML(s.name)}</h2><p class="song-meta">${s.first?.date?.slice(0,4)||'?'}—${s.last?.date?.slice(0,4)||'?'} <span aria-hidden="true">/</span> ${s.kind==='sequence'?'Complete live sequence':s.count===null?'Performance research pending':s.count+' concert listings'} <span aria-hidden="true">/</span> <a href="${escapeHTML(s.history)}" target="_blank" rel="noopener">${s.kind==='sequence'?'Sequence ranking':'History'} ${icon('external')}</a></p></div><button class="play-all" id="play-all" ${available.length?'':'disabled'}>${available.length===3?'<span class="play-bars" aria-hidden="true"><i></i><i></i><i></i></span>':icon('play')} ${available.length===3?'Play all three':`Play ${available.length} available`}</button></div><div class="cards">${['first','last','best'].map((k,i)=>card(s,k,i)).join('')}</div><p class="caveat">${s.kind==='sequence'?'First and last refer to the complete sequence in order, not the individual songs. “Best” uses HeadyVersion’s separate sequence ranking.':'First and last are documented dates, not always surviving tapes. “Best” follows HeadyVersion’s individual-song votes. Linked sequence rankings are separate.'} Votes are a dated snapshot, not a universal verdict. <button type="button" id="explain" data-open-method aria-haspopup="dialog" aria-controls="method">How picks work ${icon('info')}</button></p><p class="caveat report-line">Something wrong? <a class="report-link" href="${escapeHTML(reportHref(s.name))}">Report a mistake</a></p>`;$('#detail').querySelectorAll('[data-play]').forEach(b=>b.onclick=()=>{queue=[];play(s,b.dataset.play)});$('#play-all').onclick=()=>{queue=available.map(k=>({s,k}));const item=queue.shift();if(item)play(item.s,item.k)};if(updateURL)history.replaceState(null,'','#'+encodeURIComponent(name));return true}
async function play(s,k,part=0){
 const p=s[k],tracks=tracksFor(p);if(!tracks[part])return;
 const token=++playToken;audio.pause();playing={s,k,part};
 $('#now-type').textContent=labels[k].toUpperCase();$('#now-title').textContent=s.name;
 $('#now-date').textContent=date(p.date)+(tracks.length>1?` · ${part+1}/${tracks.length}: ${tracks[part].title}`:p.duration?' · '+p.duration:'');
 $('#player-status').textContent='Loading tape…';$('#recording-link').hidden=!p.recording;$('#recording-link').href=p.recording||'';
 audio.src=tracks[part].url;
 try{await audio.play();if(token===playToken)$('#player-status').textContent=''}
 catch(e){if(token!==playToken)return;$('#player-status').textContent=e.name==='NotAllowedError'?'Tap Play on the player to continue.':'Tape unavailable. Try “Open recording”.';if(e.name!=='NotAllowedError')queue=[]}
}
function advanceTape(){
 if(playing&&playing.part+1<tracksFor(playing.s[playing.k]).length){play(playing.s,playing.k,playing.part+1);return}
 const next=queue.shift();if(next)play(next.s,next.k);else $('#player-status').textContent='End of tape.';
}
audio.addEventListener('playing',()=>{$('#player-status').textContent=''});
audio.addEventListener('waiting',()=>{$('#player-status').textContent='Buffering…'});
audio.addEventListener('error',()=>{$('#player-status').textContent='Tape unavailable. Try “Open recording”.';queue=[]});
audio.addEventListener('ended',advanceTape);
$('#sort').addEventListener('change',()=>{renderList();$('#songs').scrollTop=0});
$('#search').addEventListener('input',renderList);$('#search').addEventListener('keydown',e=>{if(e.key==='Enter'&&filtered().length){selectSong(filtered()[0].name);$('#detail h2').setAttribute('tabindex','-1');$('#detail h2').focus()}});
window.addEventListener('hashchange',()=>{try{const h=decodeURIComponent(location.hash.slice(1));if(h==='this-day')showThisDay(new Date(),false);else selectSong(h,false)}catch{}});
fetch('songs.json').then(r=>{if(!r.ok)throw Error('Collection unavailable');return r.json()}).then(data=>{songs=data;let hash='';try{hash=decodeURIComponent(location.hash.slice(1))}catch{}if(hash==='this-day'){selectSong(songs[Math.floor(Math.random()*songs.length)].name,false);showThisDay(new Date(),false)}else selectSong(songs.find(s=>s.name===hash)?.name||songs[Math.floor(Math.random()*songs.length)].name);if(document.modelContext?.registerTool){try{Promise.resolve(document.modelContext.registerTool({name:'select_grateful_dead_song',title:'Select a Grateful Dead song',description:'Search the collection and open one song’s first, last and HeadyVersion-favorite performances. Does not start audio.',inputSchema:{type:'object',properties:{name:{type:'string'}},required:['name'],additionalProperties:false},annotations:{readOnlyHint:false},execute(input){if(!input||typeof input.name!=='string')throw Error('A song name is required');const s=songs.find(s=>s.name.toLowerCase()===input.name.toLowerCase());if(!s)throw Error('Song not in this collection');$('#search').value='';selectSong(s.name);return {name:s.name,performances:['first','last','best'].map(k=>({type:k,date:s[k]?.date,playable:playable(s[k])}))}}})).catch(()=>{})}catch{}}}).catch(()=>{$('#detail').innerHTML='<h2>The tapes didn’t load.</h2><p>Please reload to try again.</p>';$('#songs').innerHTML='';$('#count').textContent='Collection unavailable'});

const toggle=$('#audio-toggle'),seek=$('#audio-seek'),mute=$('#audio-mute');
const clock=n=>Number.isFinite(n)?`${Math.floor(n/60)}:${String(Math.floor(n%60)).padStart(2,'0')}`:'0:00';
function syncAudio(){toggle.disabled=!audio.getAttribute('src');toggle.innerHTML=icon(audio.paused?'play':'pause');toggle.setAttribute('aria-label',audio.paused?'Play audio':'Pause audio');const duration=audio.duration;seek.disabled=!Number.isFinite(duration)||duration<=0;seek.max=seek.disabled?100:duration;seek.value=audio.currentTime||0;seek.setAttribute('aria-valuetext',`${clock(audio.currentTime)} of ${clock(duration)}`);$('#audio-elapsed').textContent=clock(audio.currentTime);$('#audio-duration').textContent=clock(duration);mute.innerHTML=icon(audio.muted?'mute':'volume');mute.setAttribute('aria-label',audio.muted?'Unmute audio':'Mute audio');document.querySelectorAll('.audio-controls input[type=range]').forEach(i=>i.style.setProperty('--p',(i.max-i.min?(i.value-i.min)/(i.max-i.min)*100:0)+'%'))}
toggle.addEventListener('click',async()=>{if(audio.paused){try{await audio.play()}catch{$('#player-status').textContent='Tape unavailable. Try “Open recording”.'}}else audio.pause()});
seek.addEventListener('input',()=>{if(Number.isFinite(audio.duration))audio.currentTime=Number(seek.value)});
mute.addEventListener('click',()=>{audio.muted=!audio.muted;syncAudio()});
$('#audio-volume').addEventListener('input',e=>{audio.volume=Number(e.target.value);audio.muted=audio.volume===0;syncAudio()});

['loadedmetadata','durationchange','timeupdate','play','pause','ended','emptied','volumechange','loadstart'].forEach(name=>audio.addEventListener(name,syncAudio));
audio.controls=false;$('.audio-controls').hidden=false;syncAudio();
function reservePlayerSpace(){document.documentElement.style.setProperty('--player-space',`${Math.ceil($('.player').getBoundingClientRect().height)+32}px`)}
if(typeof ResizeObserver==='function')new ResizeObserver(reservePlayerSpace).observe($('.player'));
window.addEventListener('resize',reservePlayerSpace);reservePlayerSpace();

/* This day in Dead history */
const kindLabel={first:'The First',last:'The Last',best:'The Best'},DAY_CAP=5;
function dayEntries(now){
 const md=d=>String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
 const all=[];
 songs.forEach(s=>['first','last','best'].forEach((k,ki)=>{const p=s[k];if(p?.date)all.push({s,k,ki,p,md:p.date.slice(5,10)})}));
 for(const win of [0,3,7]){
  const offs={};
  for(let o=-win;o<=win;o++)offs[md(new Date(now.getFullYear(),now.getMonth(),now.getDate()+o))]=o;
  const found=all.filter(e=>e.md in offs).map(e=>({...e,off:offs[e.md]}));
  if(found.length)return {win,found};
 }
 return {win:7,found:[]};
}
function dayGroups(found){
 const g=new Map();
 found.forEach(e=>{
  const loc=(e.p.venue||'').split(' - '),key=e.p.date+'|'+(e.p.venueName||loc[0]);
  if(!g.has(key))g.set(key,{date:e.p.date,off:e.off,venue:e.p.venueName||loc[0],city:e.p.city||loc.slice(1).join(' · '),items:[]});
  g.get(key).items.push(e);
 });
 return [...g.values()].map(x=>({...x,items:x.items.sort((a,b)=>a.ki-b.ki||a.s.name.localeCompare(b.s.name))}))
  .sort((a,b)=>Math.abs(a.off)-Math.abs(b.off)||a.off-b.off||a.date.localeCompare(b.date));
}
const dayOffsetLabel=o=>o===0?'Today':o<0?`${-o} ${o===-1?'day':'days'} ago`:`in ${o} ${o===1?'day':'days'}`;
function dayTapeHTML(e,gi,i){
 const ok=playable(e.p),paper=tapeVariation(e.s,e.ki).paper,title=`${date(e.p.date)}, ${kindLabel[e.k]}: ${e.s.name}`;
 const venue=e.p.venueName||(e.p.venue||'').split(' - ')[0];
 return `<div class="day-row${i>=DAY_CAP?' day-extra':''}" ${i>=DAY_CAP?'hidden':''}><button type="button" class="day-tape ${e.k} paper-${paper}" data-day-play="${gi}:${i}" ${ok?'':'disabled'} aria-label="${ok?'Play':'No matched tape for'} ${escapeHTML(title)}"><span class="cassette-spine"><span class="spine-paper"><span class="spine-writing"><span class="spine-title"><time datetime="${e.p.date}">${compactDate(e.p.date)}</time><span aria-hidden="true"> - </span><span>${kindLabel[e.k]}</span><span>: ${escapeHTML(e.s.name)}</span></span><span class="venue">${escapeHTML(venue)}</span></span><span class="spine-icon icon-${e.ki}" aria-hidden="true"></span></span></span></button><button type="button" class="day-open" data-day-open="${gi}:${i}">Open song</button></div>`;
}
function dayGroupHTML(g,gi){
 const nPlay=g.items.filter(e=>playable(e.p)).length,extra=g.items.length-DAY_CAP;
 return `<section class="day-group"><div class="day-group-head"><div><h3>${escapeHTML(date(g.date))} · ${escapeHTML(g.venue)}</h3><p>${escapeHTML([g.city,dayOffsetLabel(g.off)].filter(Boolean).join(' · '))}</p></div>${nPlay>1?`<button type="button" class="day-play-all" data-day-all="${gi}">${icon('play')} Play all ${nPlay}</button>`:''}</div>${g.items.map((e,i)=>dayTapeHTML(e,gi,i)).join('')}${extra>0?`<button type="button" class="day-more" data-day-more="${gi}" aria-expanded="false">Show ${extra} more</button>`:''}</section>`;
}
let dayPushed=false,dayReturn=null;
function leaveThisDay(){
 if(dayPushed){dayPushed=false;history.back();return}
 selectSong((dayReturn||songs[Math.floor(Math.random()*songs.length)]).name);
}
function showThisDay(now=new Date(),push=true){
 if(!songs.length)return;
 if(push&&location.hash!=='#this-day'){history.pushState(null,'','#this-day');dayPushed=true}
 if(selected)dayReturn=selected;
 const {win,found}=dayEntries(now),groups=dayGroups(found);
 const pretty=now.toLocaleDateString('en-US',{month:'long',day:'numeric'});
 const meta=!found.length?'No tapes found within a week of today.':win===0?`${found.length} ${found.length===1?'tape':'tapes'} from this date in Dead history.`:`Nothing on ${pretty} exactly. Here’s what happened within ${win} days.`;
 selected=null;renderList();
 const d=$('#detail');
 d.innerHTML=`<div class="song-top"><div><p class="song-kicker">THIS DAY IN DEAD HISTORY</p><h2>${escapeHTML(pretty)}</h2><p class="song-meta">${meta}</p></div><button type="button" class="day-back" id="day-back">← Back to songs</button></div>${groups.map(dayGroupHTML).join('')}<p class="caveat">Matches use month and day only, from any year. “First” and “Last” are documented dates; “Best” is the HeadyVersion community favorite.</p>`;
 $('#day-back').onclick=leaveThisDay;
 const entry=v=>{const [gi,i]=v.split(':').map(Number);return groups[gi].items[i]};
 d.querySelectorAll('[data-day-play]').forEach(b=>b.onclick=()=>{const e=entry(b.dataset.dayPlay);queue=[];play(e.s,e.k)});
 d.querySelectorAll('[data-day-open]').forEach(b=>b.onclick=()=>{const n=entry(b.dataset.dayOpen).s.name;history.pushState(null,'','#'+encodeURIComponent(n));selectSong(n,false)});
 d.querySelectorAll('[data-day-all]').forEach(b=>b.onclick=()=>{queue=groups[Number(b.dataset.dayAll)].items.filter(e=>playable(e.p)).map(e=>({s:e.s,k:e.k}));const item=queue.shift();if(item)play(item.s,item.k)});
 d.querySelectorAll('[data-day-more]').forEach(b=>b.onclick=()=>{const sec=b.closest('.day-group'),open=b.getAttribute('aria-expanded')==='true';sec.querySelectorAll('.day-extra').forEach(r=>r.hidden=open);b.setAttribute('aria-expanded',String(!open));b.textContent=open?`Show ${sec.querySelectorAll('.day-extra').length} more`:'Show fewer'});
 if(push)d.scrollIntoView({behavior:'smooth',block:'start'});
}
$('#this-day').addEventListener('click',()=>showThisDay());

/* Now-playing tile shows the doodle for the tape kind (first/last/best) */
function syncArt(){const art=$('.now-art');if(playing?.k)art.dataset.kind=playing.k;art.classList.toggle('is-playing',Boolean(playing)&&!audio.paused&&!audio.ended)}
['play','playing','pause','ended','emptied','loadstart'].forEach(n=>audio.addEventListener(n,syncArt));
