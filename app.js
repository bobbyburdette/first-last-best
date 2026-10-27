'use strict';
const $=s=>document.querySelector(s), audio=$('#audio');
if(navigator.standalone||matchMedia('(display-mode: standalone)').matches)document.documentElement.classList.add('standalone');
let songs=[],selected=null,queue=[],playHistory=[],playing=null,playToken=0;
const escapeHTML=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=d=>d?new Date(d+'T12:00:00Z').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}):'Not verified';
const compactDate=d=>d?Number(d.slice(5,7))+'.'+Number(d.slice(8,10))+'.'+d.slice(2,4):'—';
const normalizeSearch=s=>s.toLowerCase().replace(/[^a-z0-9]/g,'');
/* Real page addresses (tools/build_pages.py writes a crawlable page for each) */
const slug=n=>n.toLowerCase().replace(/&/g,' and ').replace(/['’.]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,''),songPath=s=>`/song/${slug(s.name)}/`,showPath=d=>`/show/${d}/`,DAY_PATH='/this-day/';
const tracksFor=p=>p?.tracks?.length?p.tracks:p?.audio?[{url:p.audio,title:p.track||'',duration:p.duration}]:[];
const playable=p=>tracksFor(p).length>0;
const labels={first:'First documented',last:'Last documented',best:'HeadyVersion community favorite'};
const nowTypeLabel={first:'First documented',last:'Last documented',best:'The Best Version'};
function icon(name){return `<svg class="ui-icon" aria-hidden="true" focusable="false"><use href="#sketch-${name}"></use></svg>`}
const method=$('#method'),homescreen=$('#homescreen'),dialogs=[method,homescreen];let activeDialog=method,methodOpener=null,methodScroll=0,methodFallback=false;
function openMethod(opener,dlg=method){if(dialogs.some(d=>d.open))return;activeDialog=dlg;methodOpener=opener instanceof HTMLElement?opener:document.activeElement;methodScroll=window.scrollY;methodFallback=typeof dlg.showModal!=='function';if(methodFallback){dlg.setAttribute('open','');dlg.setAttribute('aria-modal','true');$('#method-backdrop').hidden=false;document.querySelectorAll('body > header, body > main, body > .player').forEach(el=>el.inert=true)}else dlg.showModal();document.body.style.top=`-${methodScroll}px`;document.body.classList.add('method-open');dlg.querySelector('.method-body').scrollTop=0;dlg.querySelector('h2').focus({preventScroll:true})}
function restoreMethod(){document.body.classList.remove('method-open');document.body.style.top='';$('#method-backdrop').hidden=true;document.querySelectorAll('body > header, body > main, body > .player').forEach(el=>el.inert=false);window.scrollTo(0,methodScroll);methodOpener?.focus({preventScroll:true})}
function closeMethod(){const dlg=activeDialog;if(!dlg.open)return;if(methodFallback){dlg.removeAttribute('open');dlg.removeAttribute('aria-modal');restoreMethod()}else {dlg.close();restoreMethod()}}
dialogs.forEach(dlg=>{dlg.addEventListener('cancel',e=>{e.preventDefault();closeMethod()});dlg.querySelector('.close').addEventListener('click',closeMethod)});
document.addEventListener('click',e=>{const trigger=e.target.closest('[data-open-method]');if(trigger){e.preventDefault();openMethod(trigger);return}const hs=e.target.closest('[data-open-homescreen]');if(hs){e.preventDefault();openMethod(hs,homescreen)}});
dialogs.forEach(dlg=>dlg.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();closeMethod()}if(e.key==='Tab'){const focusable=[...dlg.querySelectorAll('button,a[href],select,input,[tabindex="0"]')];const first=focusable[0],last=focusable.at(-1),title=dlg.querySelector('h2');if(e.shiftKey&&(document.activeElement===first||document.activeElement===title)){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}}));
function filtered(){const q=$('#search').value.toLowerCase().replace(/[^a-z0-9]/g,'');return songs.filter(s=>[s.name,...(s.aliases||[])].some(n=>normalizeSearch(n).includes(q))).sort((a,b)=>{const mode=$('#sort').value;if(mode==='rank')return (a.rank??Infinity)-(b.rank??Infinity)||a.name.localeCompare(b.name);if(mode==='first')return (a.first?.date||'9999').localeCompare(b.first?.date||'9999')||a.name.localeCompare(b.name);return a.name.localeCompare(b.name)})}
function renderList(){const list=filtered();$('#rank-note').hidden=$('#sort').value!=='rank';$('#live-note').hidden=$('#sort').value!=='live';const shows=showMatches();$('#count').textContent=shows?.length?`${list.length} ${list.length===1?'song':'songs'} · ${shows.length} ${shows.length===1?'show':'shows'}`:`${list.length} of ${songs.length} songs`;$('#songs').innerHTML=list.length||shows?.length?list.map(s=>`<button class="song-button ${s.kind==='sequence'?'sequence':''} ${selected===s?'active':''}" data-song="${escapeHTML(s.name)}" ${selected===s?'aria-current="true"':''}><span class="num">${$('#sort').value==='rank'?(s.rank?'#'+s.rank:'—'):$('#sort').value==='live'?(s.liveRank?'#'+s.liveRank:'—'):String(list.indexOf(s)+1).padStart(2,'0')}</span><span class="song-name">${escapeHTML(s.kind==='sequence'?(s.short||s.name):s.name)}${s.kind==='sequence'?'<small class="sequence-tag">Live sequence</small>':''}${$('#sort').value==='live'?'<small class="live-count">'+(s.liveRank?(s.liveApproximate?'~':'')+s.liveCount+' live plays':'No count supplied')+'</small>':''}${$('#sort').value==='first'?'<small class="live-count">'+(s.first?.date?'Debut '+compactDate(s.first.date):'No verified date')+'</small>':''}</span>${selected===s?'<span class="arrow">'+icon('next')+'</span>':''}</button>`).join('')+showListHTML(shows):`<p class="empty">No match for “${escapeHTML($('#search').value.trim())}”. This collection is over 100 of the songs fans love most, and more can be added. <a class="request-link" href="${escapeHTML(requestHref($('#search').value.trim()))}">Request it</a></p>`;$('#songs').querySelectorAll('button').forEach(b=>b.onclick=()=>{if(b.dataset.show)showShow(b.dataset.show);else selectSong(b.dataset.song);if(matchMedia('(max-width:650px)').matches)$('#detail').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth',block:'start'})})}
function tapeVariation(s,i){const seed=Array.from(s.name).reduce((n,c)=>(n*31+c.charCodeAt(0))>>>0,0);return {paper:(seed+i)%4,icon:i}}
let tapes={};
function tapeInfoHTML(p){const t=p?.identifier&&tapes[p.identifier];if(!t)return'';const bits=[t.kind,t.taper&&'Taped by '+t.taper,t.transfer&&'Transfer by '+t.transfer].filter(Boolean);const more=t.lineage||t.note;const url=p.recording||'https://archive.org/details/'+p.identifier;return `<div class="tape-info">${bits.length?`<p class="tape-line">${escapeHTML(bits.join(' · '))}</p>`:''}${more?`<details class="tape-notes"><summary>Tape notes</summary>${t.lineage?`<p><b>Lineage</b> ${escapeHTML(t.lineage)}</p>`:''}${t.note?`<p>“${escapeHTML(t.note)}”</p>`:''}<a href="${escapeHTML(url)}" target="_blank" rel="noopener">Full notes on archive.org ${icon('external')}</a></details>`:''}</div>`}
function card(s,k,i){const variation=tapeVariation(s,i);const p=s[k];const hasAudio=playable(p);const location=p?.venue?.split(' - ')||[];const venue=p?.venueName||location[0]||'No verified selection';const city=p?.city||location.slice(1).join(' · ');let note=k==='best'?(p?.sourceType==='headyversion'?`${p.votes} HeadyVersion votes · Checked ${date(p.checkedAt)}. ${p.ties?.length?'Tied for the top vote with '+p.ties.map(t=>date(t.date)).join(', ')+'. Displaying the first entry listed.':(p.note||(s.kind==='sequence'?'Highest-voted complete sequence.':'Highest-voted entry in this song category.'))}`:'Best not yet verified.'):(p?.note||'Earliest concert listing in source; early histories may be incomplete.');if(k==='last')note=p?.note||'Last concert listing with the original Grateful Dead.';if(s.kind==='sequence'&&k==='first')note=p?.note||'First documented complete sequence.';if(s.researchPending&&k!=='best')note='Performance details and recordings have not been verified yet.';if(p?.combined&&s.kind!=='sequence'&&/>\s*\S/.test(p.track))note+=' This track includes both songs: '+p.track.replace(/\s*-*>+\s*/g,' > ')+(/[?!.]$/.test(p.track)?'':'.');if(s.kind==='sequence'&&hasAudio)note+=` Plays the full sequence · ${p.tracks.length} recording ${p.tracks.length===1?'track':'tracks'}.`;if(p?.date&&!hasAudio)note+=' No complete matched tape found for this date.';
if(k==='best'&&p?.sequence)note+=' Votes here are for the individual-song category; the sequence has a separate ranking.';
const runnerEmptyHTML='<span class="runner runner-empty" aria-hidden="true"><span class="runner-spine runner-spine-scratched"></span><span class="runner-votes">Missing Tape</span></span>';
const paperColors=['#fffdf2','#e9f0da','#f7e0e0','#f8edc7'];
const runnersUpHTML=k==='best'&&p?.runnersUp?.length?`<div class="runners-up"><p class="runners-label">Next 2 favs</p><div class="runners-row">${p.runnersUp.map((r,ri)=>{const paper=paperColors[tapeVariation(s,3+ri).paper];return r.audio?`<button type="button" class="runner" data-play-runner="${ri}" aria-label="Play ${escapeHTML(r.venue)}, ${date(r.date)}, ${r.votes} votes"><span class="runner-spine"><span class="runner-spine-paper" style="background-color:${paper}"><span class="runner-spine-date">${compactDate(r.date)}</span></span></span><span class="runner-votes"><b>${r.votes}</b> votes</span></button>`:`<a class="runner" href="${escapeHTML(r.headyHref)}" target="_blank" rel="noopener" aria-label="Open ${escapeHTML(r.venue)} on HeadyVersion, ${date(r.date)}, ${r.votes} votes"><span class="runner-spine"><span class="runner-spine-paper" style="background-color:${paper}"><span class="runner-spine-date">${compactDate(r.date)}</span></span></span><span class="runner-votes"><b>${r.votes}</b> votes</span></a>`;}).join('')}${p.runnersUp.length<2?runnerEmptyHTML:''}</div></div>`:'';
return `<article class="tape ${k} paper-${variation.paper}"><div class="tape-band"><span class="tape-band-title"><b>${['The First','The Last','The Best'][i]}</b><span aria-hidden="true"> - </span>${escapeHTML(s.short||s.name)}</span></div><div class="cassette-spine"${hasAudio?` data-play="${k}"`:''}><div class="spine-paper"><div class="spine-writing"><h3 class="venue" title="${escapeHTML(venue)}"><time datetime="${p?.date||''}" title="${date(p?.date)}">${p?.date?compactDate(p.date):'?.?.??'}</time><span aria-hidden="true"> - </span>${escapeHTML(venue)}</h3></div><span class="spine-icon icon-${variation.icon}" role="img" aria-label="Grateful Dead ${['rose','skull','lightning bolt'][variation.icon]} sketch"></span></div></div>${city?`<p class="city">${escapeHTML(city)}</p>`:''}<p class="tape-note">${escapeHTML(note)}</p>${tapeInfoHTML(p)}<div class="tape-actions"><button data-play="${k}" ${hasAudio?'':'disabled'} aria-label="${hasAudio?'Play':'Audio unavailable for'} ${labels[k]} ${escapeHTML(s.name)}">${hasAudio?icon('play')+(s.kind==='sequence'?' Play sequence':' Play Song'):!p?.date?'Not yet verified':s.researchPending&&k!=='best'?'Research pending':'No matched tape'}</button>${hasAudio&&p?.identifier?`<button data-play-show="${k}" aria-label="Play Full Show ${escapeHTML(venue)}, ${date(p.date)}">${icon('play')} Play Full Show</button>`:''}</div><div class="source-links">${k==='best'&&p?.sequence?`<a href="${escapeHTML(p.sequence.source)}" target="_blank" rel="noopener">Sequence ranking ${icon('external')}</a>`:''}${p?.source?`<a${k==='best'?' class="vote-link"':''} href="${escapeHTML(p.source)}" target="_blank" rel="noopener">${k==='best'?'Not your favorite? Vote at HeadyVersion':p.sourceLabel||'Setlist'} ${icon('external')}</a>`:''}${p?.additionalSource?`<a href="${escapeHTML(p.additionalSource)}" target="_blank" rel="noopener">Date dispute ${icon('external')}</a>`:''}${p?.recording?`<a href="${escapeHTML(p.recording)}" target="_blank" rel="noopener">Recording ${icon('external')}</a>`:p?.archiveSearch?`<a href="${escapeHTML(p.archiveSearch)}" target="_blank" rel="noopener">Search tapes ${icon('external')}</a>`:''}</div>${runnersUpHTML}</article>`}
const requestHref=q=>{const to=['mountaineerbob','gmail.com'].join('@');const body=`Song I'd like added: ${q||''}\n\nWhy it belongs (optional):\n`;return 'mailto:'+to+'?subject='+encodeURIComponent('Song request for First Last Best'+(q?': '+q:''))+'&body='+encodeURIComponent(body)};
$('#request-song').href=requestHref('');$('#request-song-modal').href=requestHref('');
const reportHref=name=>{const to=['mountaineerbob','gmail.com'].join('@');const body=`Song: ${name}\nPage: https://firstlastbest.com/#${encodeURIComponent(name)}\n\nWhich card (The First, The Last, or The Best)?\n\nWhat's wrong, and what should it say?\n\nA link to a source, if you have one:\n`;return 'mailto:'+to+'?subject='+encodeURIComponent('Mistake on First Last Best: '+name)+'&body='+encodeURIComponent(body)};

let tracking=false;function track(path,title){if(!tracking)return;try{window.goatcounter?.count?.({path,title,event:true})}catch{}}
function selectSong(name,updateURL=true){const s=songs.find(s=>s.name===name);if(!s)return false;const dsb=$('#day-shows-box');if(dsb){dsb.hidden=true;dsb.innerHTML=''}document.body.classList.remove('is-day');selected=s;renderList();const available=['first','last','best'].filter(k=>playable(s[k]));$('#detail').innerHTML=`<div class="song-top"><div><p class="song-kicker">THE GRATEFUL DEAD</p><h2>${escapeHTML(s.name)}</h2><p class="song-meta">${s.first?.date?.slice(0,4)||'?'}—${s.last?.date?.slice(0,4)||'?'} <span aria-hidden="true">/</span> ${s.kind==='sequence'?'Complete live sequence':s.count===null?'Performance research pending':s.count+' concert listings'} <span aria-hidden="true">/</span> <a href="${escapeHTML(s.history)}" target="_blank" rel="noopener">${s.kind==='sequence'?'Sequence ranking':'History'} ${icon('external')}</a></p></div><button class="play-all" id="play-all" ${available.length?'':'disabled'}>${available.length===3?'<span class="play-bars" aria-hidden="true"><i></i><i></i><i></i></span>':icon('play')} ${available.length===3?'Play all three':`Play ${available.length} available`}</button></div><div class="cards">${['first','last','best'].map((k,i)=>card(s,k,i)).join('')}</div><p class="caveat">${s.kind==='sequence'?'First and last refer to the complete sequence in order, not the individual songs. “Best” uses HeadyVersion’s separate sequence ranking.':'First and last are documented dates, not always surviving tapes. “Best” follows HeadyVersion’s individual-song votes. Linked sequence rankings are separate.'} Votes are a dated snapshot, not a universal verdict. <button type="button" id="explain" data-open-method aria-haspopup="dialog" aria-controls="method">How picks work ${icon('info')}</button></p><p class="caveat report-line">Something wrong? <a class="report-link" href="${escapeHTML(reportHref(s.name))}">Report a mistake</a></p>`;$('#detail').querySelectorAll('[data-play]').forEach(b=>b.onclick=()=>{queue=[];playHistory=[];play(s,b.dataset.play)});$('#detail').querySelectorAll('[data-play-show]').forEach(b=>b.onclick=()=>playShow(s,b.dataset.playShow));$('#detail').querySelectorAll('[data-play-runner]').forEach(b=>b.onclick=()=>{queue=[];playHistory=[];const ri=Number(b.dataset.playRunner);play(s,'best',0,null,null,s.best.runnersUp[ri])});$('#play-all').onclick=()=>{queue=available.map(k=>({s,k}));playHistory=[];const item=queue.shift();if(item)play(item.s,item.k)};if(updateURL)history.replaceState(null,'',songPath(s));track('song/'+s.name,s.name);return true}
async function play(s,k,part=0,tracksOverride=null,showMeta=null,perfOverride=null){
 const p=perfOverride||s[k],tracks=tracksOverride||tracksFor(p);if(!tracks[part])return;if(part===0)track('play/'+s.name+'/'+k,s.name+' · '+k);
 const token=++playToken;$('.player').classList.remove('is-idle');audio.pause();playing={s,k,part,tracks,show:showMeta};
 if(showMeta){
  $('#now-type').textContent='FULL SHOW';$('#now-title').textContent=showMeta.venue;
  $('#now-date').textContent=date(p.date)+` · Track ${part+1}/${tracks.length}: ${tracks[part].title}`;
 }else{
  $('#now-type').textContent=(perfOverride?'Fan favorite':nowTypeLabel[k]).toUpperCase();$('#now-title').textContent=s.name;
  $('#now-date').textContent=date(p.date)+(tracks.length>1?` · ${part+1}/${tracks.length}: ${tracks[part].title}`:p.duration?' · '+p.duration:'');
 }
 $('#player-status').textContent='Loading tape…';$('#recording-link').hidden=!p.recording;$('#recording-link').href=p.recording||'';
 audio.src=tracks[part].url;
 syncTrackNav();
 try{await audio.play();if(token===playToken)$('#player-status').textContent=''}
 catch(e){if(token!==playToken)return;$('#player-status').textContent=e.name==='NotAllowedError'?'Tap Play on the player to continue.':'Tape unavailable. Try “Open recording”.';if(e.name!=='NotAllowedError'){queue=[];playHistory=[]}}
}
function advanceTape(){
 if(playing&&playing.part+1<playing.tracks.length){play(playing.s,playing.k,playing.part+1,playing.tracks,playing.show);return}
 goNext();
}
function goNext(){
 if(!queue.length){$('#player-status').textContent='End of tape.';syncTrackNav();return}
 if(playing)playHistory.push({s:playing.s,k:playing.k});
 const next=queue.shift();play(next.s,next.k);
}
function goPrev(){
 if(!playHistory.length)return;
 if(playing)queue.unshift({s:playing.s,k:playing.k});
 const prev=playHistory.pop();play(prev.s,prev.k);
}
function stepTrack(delta){
 if(!playing)return;
 const dest=playing.part+delta;
 if(dest>=0&&dest<playing.tracks.length){play(playing.s,playing.k,dest,playing.tracks,playing.show);return}
 if(delta>0)goNext();else goPrev();
}
function syncTrackNav(){
 const hasNext=!!playing&&(playing.part+1<playing.tracks.length||queue.length>0);
 const hasPrev=!!playing&&(playing.part>0||playHistory.length>0);
 const show=hasNext||hasPrev;
 $('#track-prev').hidden=$('#track-next').hidden=!show;
 if(show){$('#track-prev').disabled=!hasPrev;$('#track-next').disabled=!hasNext}
}
function showTracksFromMeta(meta,identifier){
 let files=(meta.files||[]).filter(f=>/\.mp3$/i.test(f.name||''));
 const plain=files.filter(f=>!/_vbr\.mp3$/i.test(f.name));
 if(plain.length)files=plain;
 files=files.map(f=>({...f,n:parseInt((f.track||'').match(/\d+/)?.[0]||'',10)}))
   .sort((a,b)=>(Number.isFinite(a.n)?a.n:1e6)-(Number.isFinite(b.n)?b.n:1e6)||a.name.localeCompare(b.name));
 return files.map(f=>({url:`https://archive.org/download/${identifier}/${encodeURIComponent(f.name)}`,title:f.title||f.name.replace(/\.mp3$/i,''),duration:f.length||null}));
}
async function playShow(s,k,startAt=0,known=null){
 const p=s[k];if(!p?.identifier)return;
 queue=[];playHistory=[];const token=++playToken;playing=null;
 $('.player').classList.remove('is-idle');audio.pause();audio.removeAttribute('src');audio.load();
 const loc=(p.venue||'').split(' - '),venue=p.venueName||loc[0]||'Unknown venue';
 $('#now-type').textContent='FULL SHOW';$('#now-title').textContent=venue;$('#now-date').textContent=date(p.date)+' · Loading the whole show…';
 $('#player-status').textContent='Loading the whole show…';$('#recording-link').hidden=!p.recording;$('#recording-link').href=p.recording||'';
 syncTrackNav();
 let tracks=null;
 try{
  tracks=known||await showSetlistTracks(p.identifier);
 }catch(e){tracks=null}
 if(token!==playToken)return;
 if(!tracks||!tracks.length){$('#player-status').textContent='Could not load the whole show. Try “Open recording”.';return}
 play(s,k,startAt,tracks,{venue});
}
audio.addEventListener('playing',()=>{$('#player-status').textContent=''});
audio.addEventListener('waiting',()=>{$('#player-status').textContent='Buffering…'});
audio.addEventListener('error',()=>{$('#player-status').textContent='Tape unavailable. Try “Open recording”.';queue=[];playHistory=[]});
audio.addEventListener('ended',advanceTape);
$('#sort').addEventListener('change',()=>{renderList();$('#songs').scrollTop=0});
$('#search').addEventListener('input',renderList);$('#search').addEventListener('keydown',e=>{if(e.key!=='Enter')return;const sh=showMatches();if(filtered().length)selectSong(filtered()[0].name);else if(sh?.length)showShow(sh[0].d);else return;$('#detail h2').setAttribute('tabindex','-1');$('#detail h2').focus()});
function routeFromURL(initial){
 let p=location.pathname,h='';try{h=decodeURIComponent(location.hash.slice(1))}catch{}
 if(h){const s=songs.find(x=>x.name===h),np=h==='this-day'?DAY_PATH:h.startsWith('show-')?showPath(h.slice(5)):s?songPath(s):null;if(np){history.replaceState(null,'',np);p=np}}
 const m=p.match(/^\/(song|show)\/([^/]+)\/?$/),random=()=>songs[Math.floor(Math.random()*songs.length)].name;
 if(initial&&(p===DAY_PATH||m?.[1]==='show')){selectSong(random(),false);selected=null}
 if(p===DAY_PATH)return showThisDay(new Date(),false);
 if(m?.[1]==='show')return openShow(m[2],false).then(ok=>{if(!ok)history.replaceState(null,'','/')});
 const s=m?.[1]==='song'&&songs.find(x=>slug(x.name)===m[2]);
 if(s)return selectSong(s.name,false);
 if(p!=='/')history.replaceState(null,'','/');
 selectSong((initial?null:dayReturn||selected)?.name||random(),false);
}
window.addEventListener('popstate',()=>routeFromURL(false));window.addEventListener('hashchange',()=>routeFromURL(false));
Promise.all([fetch('/songs.json?v=28').then(r=>{if(!r.ok)throw Error('Collection unavailable');return r.json()}),fetch('/tapes.json?v=3').then(r=>r.ok?r.json():{}).catch(()=>({}))]).then(([data,t])=>{tapes=t||{};songs=data;routeFromURL(true);tracking=true;if(document.modelContext?.registerTool){try{Promise.resolve(document.modelContext.registerTool({name:'select_grateful_dead_song',title:'Select a Grateful Dead song',description:'Search the collection and open one song’s first, last and HeadyVersion-favorite performances. Does not start audio.',inputSchema:{type:'object',properties:{name:{type:'string'}},required:['name'],additionalProperties:false},annotations:{readOnlyHint:false},execute(input){if(!input||typeof input.name!=='string')throw Error('A song name is required');const s=songs.find(s=>s.name.toLowerCase()===input.name.toLowerCase());if(!s)throw Error('Song not in this collection');$('#search').value='';selectSong(s.name);return {name:s.name,performances:['first','last','best'].map(k=>({type:k,date:s[k]?.date,playable:playable(s[k])}))}}})).catch(()=>{})}catch{}}}).catch(()=>{$('#detail').innerHTML='<h2>The tapes didn’t load.</h2><p>Please reload to try again.</p>';$('#songs').innerHTML='';$('#count').textContent='Collection unavailable'});

const toggle=$('#audio-toggle'),seek=$('#audio-seek'),mute=$('#audio-mute');
const clock=n=>Number.isFinite(n)?`${Math.floor(n/60)}:${String(Math.floor(n%60)).padStart(2,'0')}`:'0:00';
let scrubbing=false;
function syncAudio(){toggle.disabled=!audio.getAttribute('src');toggle.innerHTML=icon(audio.paused?'play':'pause');toggle.setAttribute('aria-label',audio.paused?'Play audio':'Pause audio');const duration=audio.duration;seek.disabled=!Number.isFinite(duration)||duration<=0;seek.max=seek.disabled?100:duration;if(!scrubbing)seek.value=audio.currentTime||0;seek.setAttribute('aria-valuetext',`${clock(audio.currentTime)} of ${clock(duration)}`);$('#audio-elapsed').textContent=clock(scrubbing?seek.value:audio.currentTime);$('#audio-duration').textContent=clock(duration);mute.innerHTML=icon(audio.muted?'mute':'volume');mute.setAttribute('aria-label',audio.muted?'Unmute audio':'Mute audio');document.querySelectorAll('.audio-controls input[type=range]').forEach(i=>i.style.setProperty('--p',(i.max-i.min?(i.value-i.min)/(i.max-i.min)*100:0)+'%'))}
toggle.addEventListener('click',async()=>{if(audio.paused){try{await audio.play()}catch{$('#player-status').textContent='Tape unavailable. Try “Open recording”.'}}else audio.pause()});
seek.addEventListener('pointerdown',()=>scrubbing=true);
seek.addEventListener('input',()=>{$('#audio-elapsed').textContent=clock(Number(seek.value));if(Number.isFinite(audio.duration))audio.currentTime=Number(seek.value)});
const endScrub=()=>{scrubbing=false;syncAudio()};
seek.addEventListener('pointerup',endScrub);
seek.addEventListener('pointercancel',endScrub);
seek.addEventListener('keyup',endScrub);
seek.addEventListener('blur',endScrub);
mute.addEventListener('click',()=>{audio.muted=!audio.muted;syncAudio()});
$('#track-prev').addEventListener('click',()=>stepTrack(-1));
$('#track-next').addEventListener('click',()=>stepTrack(1));
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
 const on=d=>all.filter(e=>e.md===md(d)).map(e=>({...e,off:0}));
 const found=on(now);
 let next=null;
 for(let o=1;o<=366&&!next;o++){const d=new Date(now.getFullYear(),now.getMonth(),now.getDate()+o),f=on(d);if(f.length)next={date:d,off:o,found:f}}
 return {found,next};
}
function dayGroups(found){
 const g=new Map();
 found.forEach(e=>{
  const loc=(e.p.venue||'').split(' - '),key=e.p.date;
  if(!g.has(key))g.set(key,{date:e.p.date,off:e.off,venue:e.p.venueName||loc[0],city:e.p.city||loc.slice(1).join(' · '),items:[]});
  g.get(key).items.push(e);
 });
 return [...g.values()].map(x=>({...x,items:x.items.sort((a,b)=>a.ki-b.ki||a.s.name.localeCompare(b.s.name))}))
  .sort((a,b)=>Math.abs(a.off)-Math.abs(b.off)||a.off-b.off||a.date.localeCompare(b.date));
}
let dayYear=new Date().getFullYear();
const yearsAgoLabel=d=>{const n=dayYear-Number(d.slice(0,4));return n>0?`${n} ${n===1?'year':'years'} ago today`:'Today'};
function nextUpHTML(next,empty){
 const when=next.date.toLocaleDateString('en-US',{month:'long',day:'numeric'});
 const head=next.off===1?`Tomorrow, ${when}`:`Next up: ${when}, in ${next.off} days`;
 const items=[...next.found].sort((a,b)=>a.ki-b.ki||a.s.name.localeCompare(b.s.name));
 const names=items.slice(0,4).map(e=>`${escapeHTML(e.s.short||e.s.name)} (${kindLabel[e.k].replace('The ','')})`);
 const more=items.length-names.length;
 const list=names.length>1?names.slice(0,-1).join(', ')+(more>0?', ':' and ')+names[names.length-1]:names[0];
 return `<aside class="day-next${empty?' is-lead':''}"><h3>${escapeHTML(head)}</h3><p>${list}${more>0?` and ${more} more`:''}.</p></aside>`;
}
function dayTapeHTML(e,gi,i,cap=DAY_CAP){
 const ok=playable(e.p),paper=tapeVariation(e.s,e.ki).paper,label=e.label||kindLabel[e.k];
 const venue=e.p.venueName||(e.p.venue||'').split(' - ')[0];
 return `<div class="day-row ${e.k} paper-${paper}${i>=cap?' day-extra':''}" ${i>=cap?'hidden':''}><div class="tape-band"><span class="tape-band-title"><b>${label}</b><span aria-hidden="true"> - </span>${escapeHTML(e.s.short||e.s.name)}</span></div><button type="button" class="day-spine" data-day-play="${gi}:${i}" ${ok?'':'disabled'} tabindex="-1" aria-hidden="true"><span class="cassette-spine"><span class="spine-paper"><span class="spine-writing"><span class="venue"><time datetime="${e.p.date}">${compactDate(e.p.date)}</time><span aria-hidden="true"> - </span>${escapeHTML(venue)}</span></span><span class="spine-icon icon-${e.ki}" aria-hidden="true"></span></span></span></button><div class="day-actions"><button type="button" class="day-play" data-day-play="${gi}:${i}" ${ok?'':'disabled'}>${ok?icon('play')+(e.s.kind==='sequence'?' Play sequence':' Play Song'):'No matched tape'}</button>${ok&&e.p.identifier?`<button type="button" class="day-play-show" data-day-play-show="${gi}:${i}">${icon('play')} Play Full Show</button>`:''}<button type="button" class="day-open" data-day-open="${gi}:${i}">Open song</button></div></div>`;
}
function ticketDate(iso){const dt=new Date(iso+'T12:00:00Z'),[y,m,d]=iso.split('-'),o=k=>dt.toLocaleDateString('en-US',{[k]:'short',timeZone:'UTC'}).toUpperCase();return {code:'GD'+y.slice(2)+m+d,line:`${o('weekday')} ${o('month')} ${Number(d)} ${y}`,short:`${Number(m)}/${Number(d)}/${y.slice(2)}`}}
function stripHTML(g){
 const t={first:0,last:0,best:0};g.items.forEach(e=>t[e.k]++);const td=ticketDate(g.date),n=dayYear-Number(g.date.slice(0,4));
 return `<button type="button" class="tk-strip" data-show-open="${g.date}" aria-label="Open the ${escapeHTML(date(g.date))} show at ${escapeHTML(g.venue)}"><span class="tk-strip-stub" aria-hidden="true"><span>${td.code}</span><span class="doodle d-${['first','last','best'].indexOf(g.items[0].k)}"></span></span><span class="tk-strip-body"><span class="tk-strip-venue">${escapeHTML(g.venue)}</span><span class="tk-strip-city">${escapeHTML(g.city)}</span><span class="tk-strip-date">${td.line}</span></span><span class="tk-strip-side"><span class="tk-strip-ago"><b>${n}</b> YRS AGO</span><span class="ticket-tally">${TALLY.filter(([k])=>t[k]).map(([k,l])=>`<span class="tally ${k}"><b>${t[k]}</b>${l}</span>`).join('')}</span></span><span class="tk-strip-go" aria-hidden="true">${icon('next')}</span></button>`;
}
function dayGroupHTML(g,gi){
 const nPlay=g.items.filter(e=>playable(e.p)).length,extra=g.items.length-DAY_CAP;
 return `<section class="day-group">${stripHTML(g)}${nPlay>1?`<div class="day-group-head"><button type="button" class="day-play-all" data-day-all="${gi}">${icon('play')} Play all ${nPlay}</button></div>`:''}${g.items.map((e,i)=>dayTapeHTML(e,gi,i)).join('')}${extra>0?`<button type="button" class="day-more" data-day-more="${gi}" aria-expanded="false">Show ${extra} more</button>`:''}</section>`;
}
let showsData=null;
async function loadShows(){if(showsData)return showsData;try{const r=await fetch('/shows.json?v=3');if(!r.ok)throw Error('shows unavailable');showsData=await r.json()}catch{return []}return showsData}
function pipsOn(d){const t={first:0,last:0,best:0};songs.forEach(s=>['first','last','best'].forEach(k=>{if(s[k]?.date===d)t[k]++}));const ks=Object.keys(t).filter(k=>t[k]);return ks.length?`<span class="show-pips" aria-label="${ks.map(k=>t[k]+' '+k).join(', ')}">${ks.map(k=>`<i class="pip ${k}">${t[k]}</i>`).join('')}</span>`:''}
function dayShowsHTML(list){
 const cap=list.length<=8?list.length:6,extra=list.length-cap;
 const yrs=list.length>1?`${list[0].d.slice(0,4)} to ${list[list.length-1].d.slice(0,4)}`:list[0].d.slice(0,4);
 return `<h3 class="day-section-title">Shows on this day</h3><p class="day-shows-sub">${list.length} ${list.length===1?'show':'shows'} in the Dead’s touring history, ${yrs}.</p><ul class="day-show-list">${list.map((e,i)=>`<li class="day-show${i>=cap?' day-show-extra':''}" ${i>=cap?'hidden':''}><button type="button" class="day-show-info" data-show-open="${e.d}"><span class="day-show-year">${e.d.slice(0,4)}${pipsOn(e.d)}</span><span class="day-show-venue">${escapeHTML(e.v)}</span><span class="day-show-city">${escapeHTML([e.c,yearsAgoLabel(e.d)].filter(Boolean).join(' · '))}</span></button><button type="button" class="day-show-play" data-show-play="${i}">${icon('play')} Play Full Show</button></li>`).join('')}</ul>${extra>0?`<button type="button" class="day-more" data-shows-more aria-expanded="false">Show ${extra} more</button>`:''}<p class="caveat">The list comes from Internet Archive’s Grateful Dead collection, so shows with no surviving recording are not listed.</p>`;
}
async function fillDayShows(el,md){
 const all=await loadShows(),list=all.filter(e=>e.d.slice(5)===md);
 if(!el.isConnected||!list.length)return;
 el.innerHTML=dayShowsHTML(list);el.closest('.day-shows-box')?.removeAttribute('hidden');
 el.querySelectorAll('[data-show-play]').forEach(b=>b.onclick=()=>{const e=list[Number(b.dataset.showPlay)];const p={date:e.d,venueName:e.v,venue:e.c?`${e.v} - ${e.c}`:e.v,identifier:e.id,recording:`https://archive.org/details/${e.id}`};queue=[];playHistory=[];playShow({name:e.v,show:p},'show')});
 el.querySelectorAll('[data-show-open]').forEach(b=>b.onclick=()=>openShow(b.dataset.showOpen,true));
 const more=el.querySelector('[data-shows-more]');
 if(more)more.onclick=()=>{const open=more.getAttribute('aria-expanded')==='true';el.querySelectorAll('.day-show-extra').forEach(r=>r.hidden=open);more.setAttribute('aria-expanded',String(!open));more.textContent=open?`Show ${el.querySelectorAll('.day-show-extra').length} more`:'Show fewer'};
}
let dayPushed=false,dayReturn=null;
const backLabel=()=>escapeHTML(dayReturn?`← Back to ${dayReturn.short||dayReturn.name}`:'← All songs');
function backToSongs(){selectSong((dayReturn||songs[Math.floor(Math.random()*songs.length)]).name);if(!dayReturn)$('aside').scrollIntoView({block:'start'})}
function leaveThisDay(){
 if(dayPushed){dayPushed=false;history.back();return}
 backToSongs();
}
function showThisDay(now=new Date(),push=true){track('this-day','This day');
 if(!songs.length)return;
 if(push&&location.pathname!==DAY_PATH){history.pushState(null,'',DAY_PATH);dayPushed=true}
 if(selected)dayReturn=selected;
 dayYear=now.getFullYear();const {found,next}=dayEntries(now),groups=dayGroups(found);
 const pretty=now.toLocaleDateString('en-US',{month:'long',day:'numeric'});
 const meta=found.length?'Songs first played, last played, or picked as fan favorite on this date, in any year.':`No First, Last, or Best versions fall on ${pretty}.${next?.off===1?' Check back tomorrow.':''}`;
 selected=null;renderList();
 const d=$('#detail');
 d.innerHTML=`<div class="song-top"><div><p class="song-kicker">THIS DAY IN DEAD HISTORY</p><h2>${escapeHTML(pretty)}</h2>${found.length?'':`<p class="song-meta">${meta}</p>`}</div><button type="button" class="day-back" id="day-back">${backLabel()}</button></div>${found.length?`<section class="day-flb"><h3 class="day-section-title">First, Last &amp; Best</h3><p class="day-shows-sub">${meta}</p>${groups.map(dayGroupHTML).join('')}</section>`:''}${next&&(!found.length||next.off===1)?nextUpHTML(next,!found.length):''}<p class="caveat">Matches use month and day only, from any year. “First” and “Last” are documented dates; “Best” is the HeadyVersion community favorite.</p>`;
 $('#day-back').onclick=leaveThisDay;document.body.classList.add('is-day');
 if(matchMedia('(min-width:651px)').matches){$('#day-shows-box').innerHTML='';d.querySelector(':scope>.caveat').insertAdjacentHTML('beforebegin','<section class="day-shows day-shows-inline" id="day-shows"></section>')}else $('#day-shows-box').innerHTML='<section class="day-shows" id="day-shows"></section>';
 fillDayShows($('#day-shows'),String(now.getMonth()+1).padStart(2,'0')+'-'+String(now.getDate()).padStart(2,'0'));
 const entry=v=>{const [gi,i]=v.split(':').map(Number);return groups[gi].items[i]};
 d.querySelectorAll('[data-day-play]').forEach(b=>b.onclick=()=>{const e=entry(b.dataset.dayPlay);queue=[];playHistory=[];play(e.s,e.k)});
 d.querySelectorAll('[data-day-play-show]').forEach(b=>b.onclick=()=>{const e=entry(b.dataset.dayPlayShow);queue=[];playHistory=[];playShow(e.s,e.k)});
 d.querySelectorAll('[data-day-open]').forEach(b=>b.onclick=()=>{const n=entry(b.dataset.dayOpen).s.name;history.pushState(null,'',songPath({name:n}));selectSong(n,false)});
 d.querySelectorAll('[data-show-open]').forEach(b=>b.onclick=()=>openShow(b.dataset.showOpen,true));
 d.querySelectorAll('[data-day-all]').forEach(b=>b.onclick=()=>{queue=groups[Number(b.dataset.dayAll)].items.filter(e=>playable(e.p)).map(e=>({s:e.s,k:e.k}));playHistory=[];const item=queue.shift();if(item)play(item.s,item.k)});
 d.querySelectorAll('[data-day-more]').forEach(b=>b.onclick=()=>{const sec=b.closest('.day-group'),open=b.getAttribute('aria-expanded')==='true';sec.querySelectorAll('.day-extra').forEach(r=>r.hidden=open);b.setAttribute('aria-expanded',String(!open));b.textContent=open?`Show ${sec.querySelectorAll('.day-extra').length} more`:'Show fewer'});
 if(push)d.scrollIntoView({behavior:'smooth',block:'start'});
}
$('#this-day').addEventListener('click',()=>showThisDay());
/* Find a show: dates and places typed into the song search */
const STATES={AL:'alabama',AK:'alaska',AZ:'arizona',AR:'arkansas',CA:'california',CO:'colorado',CT:'connecticut',DE:'delaware',DC:'washington dc',FL:'florida',GA:'georgia',HI:'hawaii',ID:'idaho',IL:'illinois',IN:'indiana',IA:'iowa',KS:'kansas',KY:'kentucky',LA:'louisiana',ME:'maine',MD:'maryland',MA:'massachusetts',MI:'michigan',MN:'minnesota',MS:'mississippi',MO:'missouri',MT:'montana',NE:'nebraska',NV:'nevada',NH:'new hampshire',NJ:'new jersey',NM:'new mexico',NY:'new york',NC:'north carolina',ND:'north dakota',OH:'ohio',OK:'oklahoma',OR:'oregon',PA:'pennsylvania',RI:'rhode island',SC:'south carolina',SD:'south dakota',TN:'tennessee',TX:'texas',UT:'utah',VT:'vermont',VA:'virginia',WA:'washington',WV:'west virginia',WI:'wisconsin',WY:'wyoming'};
const STATE_CODE=Object.fromEntries(Object.entries(STATES).map(([k,v])=>[v.replace(/ /g,''),k]));
const pad2=n=>String(n).padStart(2,'0'),SHOW_CAP=40;
let showIndex=null;
function stateOf(c){const t=(c||'').split(',').pop().trim(),u=t.toUpperCase().replace(/\./g,'');return STATES[u]?u:STATE_CODE[normalizeSearch(t)]||(/\bCA$/.test(t)?'CA':'')}
const VENUE_ALIAS=[[/johnfkennedy/g,'jfk'],[/oaklandalamedacounty|alamedacounty/g,'oakland'],[/henryjkaiser(conventioncenter|auditorium)/g,'kaiser'],[/^(the)/,''],[/(earlyshow|lateshow)$/,'']];
function venueKey(v,c){const city=normalizeSearch((c||'').split(',')[0]);let k=normalizeSearch((v||'').split(/ - |,|\(/)[0].replace(/theatre/gi,'theater'));VENUE_ALIAS.forEach(([re,to])=>k=k.replace(re,to));if(city&&k!==city&&k.startsWith(city))k=k.slice(city.length);return city+'|'+k}
function buildShowIndex(list){
 const byDate=new Map(list.map(e=>[e.d,{...e,picks:[]}]));
 const add=(p,item)=>{if(!p?.date)return;if(!byDate.has(p.date)){const loc=(p.venue||'').split(' - ');byDate.set(p.date,{d:p.date,v:p.venueName||loc[0],c:p.city||loc.slice(1).join(', '),id:p.identifier,picks:[]})}byDate.get(p.date).picks.push(item)};
 songs.forEach(s=>['first','last','best'].forEach((k,ki)=>add(s[k],{s,k,ki,p:s[k],off:0})));
 return [...byDate.values()].map(e=>{const st=stateOf(e.c);return {...e,st,vk:venueKey(e.v,e.c),hay:normalizeSearch([e.v,e.c,STATES[st]||''].join(' '))}}).sort((a,b)=>a.d.localeCompare(b.d));
}
const tally=e=>{const t={first:0,last:0,best:0};e.picks.forEach(x=>t[x.k]++);return t};
const TALLY=[['first','First'],['last','Last'],['best','Best']];
function parseShowQuery(raw){
 const q=raw.trim().toLowerCase();let m;
 const yr=y=>y.length===4?y:(Number(y)<50?'20':'19')+y;
 if(m=q.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/))return {date:`${m[1]}-${pad2(m[2])}-${pad2(m[3])}`};
 if(m=q.match(/^(\d{1,2})[\/.\-](\d{1,2})(?:[\/.\-](\d{2}|\d{4}))?$/))return m[3]?{date:`${yr(m[3])}-${pad2(m[1])}-${pad2(m[2])}`}:{md:`${pad2(m[1])}-${pad2(m[2])}`};
 if(m=q.match(/^([a-z]{3,})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?(?:\s+'?(\d{2}|\d{4}))?$/)){const mo=['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'].indexOf(m[1].slice(0,3))+1;if(mo)return m[3]?{date:`${yr(m[3])}-${pad2(mo)}-${pad2(m[2])}`}:{md:`${pad2(mo)}-${pad2(m[2])}`}}
 if(m=q.match(/^(?:19|')(6[5-9]|[789]\d)$/))return {year:'19'+m[1]};
 if(/^[a-z][a-z .'-]*(,\s*[a-z .]+)?$/.test(q)){const n=normalizeSearch(q);if(q.length===2)return STATES[q.toUpperCase()]?{state:q.toUpperCase()}:null;if(STATE_CODE[n])return {state:STATE_CODE[n]};if(n.length>=3)return {place:n}}
 return null;
}
function showMatches(){
 const pq=parseShowQuery($('#search').value);
 if(!pq)return null;
 if(!showIndex){if(!showsData)loadShows().then(()=>{if(showsData&&!showIndex){showIndex=buildShowIndex(showsData);renderList()}});else showIndex=buildShowIndex(showsData);if(!showIndex)return [];}
 return showIndex.filter(e=>pq.date?e.d===pq.date:pq.md?e.d.slice(5)===pq.md:pq.year?e.d.startsWith(pq.year):pq.state?e.st===pq.state:e.hay.includes(pq.place));
}
function showListHTML(list){
 if(!list?.length)return '';
 return `<p class="list-section">Shows</p>${list.slice(0,SHOW_CAP).map(e=>{const t=tally(e);return `<button class="song-button show-button" data-show="${e.d}"><span class="num">${compactDate(e.d)}</span><span class="song-name">${escapeHTML(e.v)}<small class="live-count">${escapeHTML(e.c)}</small></span>${e.picks.length?`<span class="show-pips" aria-label="${e.picks.length} First, Last, Best or fan favorite">${TALLY.filter(([k])=>t[k]).map(([k])=>`<i class="pip ${k}">${t[k]}</i>`).join('')}</span>`:''}</button>`}).join('')}${list.length>SHOW_CAP?`<p class="empty">${SHOW_CAP} of ${list.length}. Add a year or city to narrow it.</p>`:''}`;
}
function ticketHTML(e,n,t,has){
 const dt=new Date(e.d+'T12:00:00Z');
 const dow=dt.toLocaleDateString('en-US',{weekday:'short',timeZone:'UTC'}).toUpperCase(),mon=dt.toLocaleDateString('en-US',{month:'short',timeZone:'UTC'}).toUpperCase();
 const [y,m,d]=e.d.split('-'),code='GD'+y.slice(2)+m+d,v=escapeHTML(e.v),c=escapeHTML(e.c);
 const tl=has?`<div class="ticket-tally">${TALLY.filter(([k])=>t[k]).map(([k,l])=>`<span class="tally ${k}"><b>${t[k]}</b>${l}</span>`).join('')}</div>`:`<p class="ticket-none">No First, Last or Best. Still a great night.</p>`;
 return `<div class="tk tk-a tk-d"><div class="tk-a-stub" aria-hidden="true"><span>${code}</span><span class="tk-d-art"><span class="doodle d-0"></span><span class="doodle d-1"></span><span class="doodle d-2"></span></span><span>${Number(m)}/${Number(d)}/${y.slice(2)}</span></div><div class="tk-a-body"><span class="tk-d-mark doodle d-1" aria-hidden="true"></span><div class="tk-a-top"><span>${code}</span><span class="tk-kicker">WERE YOU THERE?</span><span>ADMIT ONE</span></div><p class="tk-a-band">THE GRATEFUL DEAD</p><p class="tk-a-venue">${v}</p><p class="tk-a-city">${c}</p><h2>${dow} ${mon} ${Number(d)} ${y}</h2><div class="tk-a-boxes"><span><small>SEC</small>GA</span><span><small>ROW</small>GEN</span><span><small>SEAT</small>ADM</span><span class="tk-d-foil"><small>YEARS AGO</small>${n}</span></div>${tl}</div></div>`;
}
function showShow(d,push=true){
 const e=showIndex?.find(x=>x.d===d);if(!e)return false;track('show/'+d,'Show '+d);
 if(push&&location.pathname!==showPath(d)){history.pushState(null,'',showPath(d));dayPushed=true}
 if(selected)dayReturn=selected;selected=null;renderList();
 const dsb=$('#day-shows-box');if(dsb){dsb.hidden=true;dsb.innerHTML=''}document.body.classList.remove('is-day');
 const n=new Date().getFullYear()-Number(d.slice(0,4)),[y,m,dd]=d.split('-').map(Number),t=tally(e);
 const items=[...e.picks].sort((a,b)=>a.ki-b.ki||a.s.name.localeCompare(b.s.name));
 const sameVenue=showIndex.filter(x=>x.vk===e.vk&&x.d!==d);
 const md=new Date(y,m-1,dd).toLocaleDateString('en-US',{month:'short',day:'numeric'});
 const nPlay=items.filter(x=>playable(x.p)).length;
 $('#detail').innerHTML=`<div class="show-page">${ticketHTML(e,n,t,items.length)}
 <div class="show-actions">${e.id?`<button type="button" class="show-btn primary" id="show-play-full">${icon('play')} Full show</button>`:''}${nPlay>1?`<button type="button" class="show-btn" data-day-all="0">${icon('play')} Play all ${nPlay}</button>`:''}<button type="button" class="show-btn" id="show-this-day">${escapeHTML(md)} in Dead history ${icon('next')}</button><button type="button" class="show-btn ghost" id="day-back">${backLabel()}</button></div>
 ${e.id?'<section class="setlist" id="setlist" aria-label="Setlist"><p class="sl-loading">Loading the setlist…</p></section>':''}
 ${items.length?`<div class="show-tapes">${items.map((x,i)=>dayTapeHTML(x,0,i,Infinity)).join('')}</div>`:''}
 ${sameVenue.length?`<section class="show-venue"><h3>Also at ${escapeHTML(e.v)}</h3><div class="show-chips">${sameVenue.map(x=>`<button type="button" class="show-chip${x.picks.length?' has-picks':''}" data-show="${x.d}">${compactDate(x.d)}${x.picks.length?`<i>${x.picks.length}</i>`:''}</button>`).join('')}</div></section>`:''}</div>`;
 const d0=$('#detail');
 $('#day-back').onclick=()=>{dayPushed=false;backToSongs()};
 $('#show-this-day').onclick=()=>showThisDay(new Date(new Date().getFullYear(),m-1,dd));
 const full=$('#show-play-full');if(full)full.onclick=()=>{queue=[];playHistory=[];playShow({name:e.v,show:{date:d,venueName:e.v,venue:e.c?`${e.v} - ${e.c}`:e.v,identifier:e.id,recording:`https://archive.org/details/${e.id}`}},'show')};
 d0.querySelectorAll('[data-day-play]').forEach(b=>b.onclick=()=>{queue=[];playHistory=[];const x=items[Number(b.dataset.dayPlay.split(':')[1])];play(x.s,x.k)});
 d0.querySelectorAll('[data-day-open]').forEach(b=>b.onclick=()=>{const nm=items[Number(b.dataset.dayOpen.split(':')[1])].s.name;history.pushState(null,'',songPath({name:nm}));selectSong(nm,false)});
 d0.querySelectorAll('[data-day-all]').forEach(b=>b.onclick=()=>{const list=items.filter(x=>playable(x.p)).map(x=>({s:x.s,k:x.k}));queue=list;playHistory=[];const it=queue.shift();if(it)play(it.s,it.k)});
 d0.querySelectorAll('.show-chip').forEach(b=>b.onclick=()=>showShow(b.dataset.show));
 fillSetlist(e);
 if(push)d0.scrollIntoView({behavior:'smooth',block:'start'});
 return true;
}
/* Playable setlist: the show's tape track list, written like the one taped to the stage */
const setlistCache=new Map(),NON_SONG=/^(tuning|encore break|set ?break|crowd|applause|intro|banter|dead air|stage (announcements?|banter)|soundcheck|take a step back)\b/i;
function showSetlistTracks(id){if(!setlistCache.has(id))setlistCache.set(id,fetch(`https://archive.org/metadata/${encodeURIComponent(id)}`).then(r=>{if(!r.ok)throw Error('bad status');return r.json()}).then(m=>showTracksFromMeta(m,id)).catch(()=>{setlistCache.delete(id);return null}));return setlistCache.get(id)}
const titleKey=t=>t.toLowerCase().replace(/\bsaint\b/g,'st').replace(/\bthe\b|\band\b/g,'').replace(/[^a-z0-9]/g,'').replace(/ing/g,'in').replace(/s$/,'');
let songKeys=null;
function songForTitle(t){if(!songKeys){songKeys=new Map();songs.filter(s=>s.kind!=='sequence').forEach(s=>[s.name,...(s.aliases||[])].forEach(n=>songKeys.set(titleKey(n),s)))}return songKeys.get(titleKey(t))}
function setlistHTML(tracks,e){
 const marks=new Map();e.picks.forEach(x=>(x.s.kind==='sequence'?x.s.components:[x.s.name]).forEach(n=>{const k=titleKey(n);marks.set(k,[...(marks.get(k)||[]),x.k])}));
 let n=0;
 const rows=tracks.map((t,i)=>{const raw=t.title.replace(/^\s*\d{1,2}[\s.\-_]+/,''),segue=/(-?>|→)\s*$/.test(raw),name=raw.replace(/\s*(-?>|→)\s*$/,'').trim();
  if(NON_SONG.test(name))return /encore/i.test(name)?'<li class="sl-break" aria-hidden="true">E:</li>':'';
  const song=songForTitle(name),ks=[...new Set(marks.get(titleKey(name))||[])];n++;
  return `<li class="sl-row${ks.length?' has-mark':''}" data-i="${i}"><button type="button" class="sl-play" data-sl="${i}" aria-label="Play ${escapeHTML(name)} from this show"><span class="sl-num">${n}</span><span class="sl-name">${escapeHTML(name)}${segue?'<span class="sl-seg" aria-label="segues into"> &gt;</span>':''}</span>${ks.map(k=>`<span class="tally ${k}">${k}</span>`).join('')}<span class="sl-time">${escapeHTML((t.duration||'').replace(/^0(\d:)/,'$1'))}</span></button>${song?`<a class="sl-song" href="${songPath(song)}" data-sl-song="${escapeHTML(song.name)}" aria-label="${escapeHTML(song.name)}: first, last and best">${icon('next')}</a>`:'<span class="sl-song" aria-hidden="true"></span>'}</li>`}).join('');
 return `<div class="sl-paper"><h3 class="sl-title">Setlist</h3><p class="sl-hint">Tap a song to play it from this tape.</p><ol class="sl-list">${rows}</ol></div>`;
}
async function fillSetlist(e){
 const el=$('#setlist');if(!el||!e.id)return;
 const tracks=await showSetlistTracks(e.id);if(!el.isConnected)return;
 if(!tracks?.length){el.remove();return}
 el.innerHTML=setlistHTML(tracks,e);el._tracks=tracks;
 const p={date:e.d,venueName:e.v,venue:e.c?`${e.v} - ${e.c}`:e.v,identifier:e.id,recording:`https://archive.org/details/${e.id}`};
 el.querySelectorAll('[data-sl]').forEach(b=>b.onclick=()=>{queue=[];playHistory=[];playShow({name:e.v,show:p},'show',Number(b.dataset.sl),tracks)});
 el.querySelectorAll('[data-sl-song]').forEach(a=>a.onclick=ev=>{ev.preventDefault();history.pushState(null,'',a.getAttribute('href'));selectSong(a.dataset.slSong,false)});
 markSetlist();
}
function markSetlist(){const el=$('#setlist');if(!el?._tracks)return;el.querySelectorAll('.sl-row').forEach(r=>r.classList.toggle('is-playing',playing?.tracks===el._tracks&&Number(r.dataset.i)===playing.part))}
['play','loadstart','emptied'].forEach(n=>audio.addEventListener(n,markSetlist));
async function openShow(d,push){if(!showIndex){await loadShows();if(!showsData)return false;showIndex=buildShowIndex(showsData)}return showShow(d,push)}
$('#search').addEventListener('focus',()=>{loadShows()},{once:true});

/* Now-playing tile shows the doodle for the tape kind (first/last/best) */
function syncArt(){const art=$('.now-art');if(playing?.k)art.dataset.kind=playing.k;art.classList.toggle('is-playing',Boolean(playing)&&!audio.paused&&!audio.ended)}
['play','playing','pause','ended','emptied','loadstart'].forEach(n=>audio.addEventListener(n,syncArt));
/* Reload a resumed home-screen app when a newer build is live */
(()=>{const ver=d=>[d.match?.(/app\.js\?v=\d+/)?.[0],d.match?.(/style\.css\?v=\d+/)?.[0]].join('|');const cur=ver(document.documentElement.innerHTML);let last=0;
async function check(){if(Date.now()-last<60000)return;last=Date.now();try{const r=await fetch('./?update-check='+Date.now(),{cache:'no-store'});if(!r.ok)return;const lm=r.headers.get('last-modified')||'',liveAt=Date.parse(lm),loadedAt=Date.parse(document.lastModified),live=ver(await r.text());const newer=(live!=='|'&&live!==cur)||(liveAt&&loadedAt&&liveAt-loadedAt>1000);if(!newer||!(audio.paused||audio.ended))return;const key=live+lm;try{if(sessionStorage.getItem('flb-update')===key)return;sessionStorage.setItem('flb-update',key)}catch{return}location.reload()}catch{}}
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')check()});addEventListener('pageshow',e=>{if(e.persisted)check()});setTimeout(check,3000)})();
