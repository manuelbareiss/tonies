'use strict';
const $ = id => document.getElementById(id);
const state = {entries: [], filtered: [], page: 0, size: 24, token: '', selected: null, detail: null, busy: false, jobs: [], view: 'catalog'};
const labels = {catalog: 'tonie_library', write: 'put_a_story_on_a_tag', read: 'check_a_tag', doctor: 'check_your_setup', activity: 'recent_activity'};
let language = 'en';
function t(key, values = {}) {
 const template = window.tonieLocales[language][key] ?? window.tonieLocales.en[key] ?? key;
 return template.replace(/\{(\w+)\}/g, (_, name) => values[name] ?? '');
}
function applyLanguage(next = language) {
 language = next === 'de' ? 'de' : 'en';
 document.documentElement.lang = language;
 document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
 for (const attr of ['placeholder', 'aria-label']) {
  document.querySelectorAll(`[data-i18n-${attr}]`).forEach(el => el.setAttribute(attr, t(el.getAttribute(`data-i18n-${attr}`))));
 }
 const toggle = $('language-toggle');
 toggle.textContent = t('language_toggle_text');
 toggle.setAttribute('aria-label', t('language_toggle_label'));
 toggle.title = toggle.getAttribute('aria-label');
 const dark = document.documentElement.dataset.theme === 'dark';
 $('theme-toggle').title = t(dark ? 'switch_to_light_mode' : 'switch_to_dark_mode');
 $('theme-toggle').setAttribute('aria-label', t('dark_mode'));
 document.title = t('page_title');
 $('breadcrumb').textContent = `${t('your_tonies')} / ${t(labels[state.view] || labels.catalog)}`;
 $('port-summary').textContent = $('serial-port').value || t('reader_selected_automatically');
 if (state.entries.length) { populateFilters(); renderCatalog(); }
 if (state.detail && $('detail-dialog').open) renderDetail(state.detail);
 renderHistory();
}
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid = value => value.match(/.{1,2}/g)?.join(' ') || value;
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').hidden = true, 4500); }
async function api(path, body) {
 const response = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json','X-Toolbox-Token':state.token}, body:JSON.stringify(body)} : {});
 const data = await response.json();
  if (!response.ok) throw new Error(data.error || t('the_request_could_not_be_completed'));
 return data;
}
function showView(view) {
 if (!labels[view]) view = 'catalog';
 state.view = view;
 document.querySelectorAll('.view').forEach(el => el.hidden = el.id !== `view-${view}`);
 document.querySelectorAll('[data-view]').forEach(el => {el.classList.toggle('active', el.dataset.view === view); el.setAttribute('aria-current', el.dataset.view === view ? 'page' : 'false');});
   $('breadcrumb').textContent = `${t('your_tonies')} / ${t(labels[view])}`;
 location.hash = view;
 if (view === 'activity') renderHistory();
}
function populateFilters() {
  for (const [id, field, label] of [['language','language','all_languages'],['series','series','all_series']]) {
  const current = $(id).value;
  const values = [...new Set(state.entries.filter(e => id !== 'series' || !$('language').value || e.language === $('language').value).map(e => e[field]))].sort((a,b) => a.localeCompare(b));
  $(id).replaceChildren(new Option(t(label), ''), ...values.map(v => new Option(v,v)));
  if (values.includes(current)) $(id).value = current;
 }
}
async function loadCatalog() {
 const data = await api('/api/catalog');
 state.entries = data.tonies;
 $('nav-count').textContent = state.entries.length;
 populateFilters(); filter();
}
let filterVersion = 0;
async function filter() {
 const version = ++filterVersion;
 const query = $('search').value.trim();
 let entries = state.entries;
 if(query) {
   $('showing').textContent=t('finding_your_stories');
  try {entries = (await api(`/api/search?q=${encodeURIComponent(query)}`)).tonies;}
  catch(error) {if(version === filterVersion)toast(error.message);return;}
 }
 if(version !== filterVersion) return;
 state.filtered = entries.filter(e => (!$('language').value || e.language === $('language').value) && (!$('series').value || e.series === $('series').value));
 const field = $('sort').value === 'relevance' ? (query ? null : 'series') : $('sort').value;
 if(field)state.filtered.sort((a,b) => a[field].localeCompare(b[field]) || a.name.localeCompare(b.name) || a.language.localeCompare(b.language));
 state.page = 0; renderCatalog();
}
function colorFor(e) { let hash=0; for (const c of e.series) hash=(hash*31+c.charCodeAt(0))|0; return Math.abs(hash)%6; }
function renderCatalog() {
 const count = state.filtered.length, start=state.page*state.size;
 $('result-count').textContent=count;
  $('showing').textContent = count ? t('catalog_showing', {start:start+1, end:Math.min(start+state.size,count), count:count.toLocaleString(language)}) : t('no_matching_tonies');
  $('page-info').textContent = t('catalog_page', {page:state.page+1, pages:Math.max(1, Math.ceil(count/state.size))});
 $('prev-page').disabled = !state.page; $('next-page').disabled = start+state.size >= count;
 $('empty').hidden = !!count;
 $('catalog-grid').innerHTML = state.filtered.slice(start,start+state.size).map(e => {
  const initials = e.name.split(/[\s-]+/).filter(Boolean).slice(0,2).map(v => v[0]).join('');
   return `<button class="tonie-card palette-${colorFor(e)}" data-entry="${escapeHTML(e.id)}"><div class="card-art"><span class="language-chip">${escapeHTML(e.language)}</span><div class="character-mark"><span>${escapeHTML(initials)}</span><i></i></div><span class="card-arrow">↗</span></div><div class="card-copy"><span class="card-series">${escapeHTML(e.series || t('standalone_tonie'))}</span><h3>${escapeHTML(e.name)}</h3><span class="card-bottom"><span class="tiny-tag">◇</span> ${t('nfc_dump_available')} <span>→</span></span></div></button>`;
 }).join('');
}
function resetFilters() { $('search').value=''; $('language').value=''; $('series').value=''; populateFilters(); filter(); }
async function openDetail(id) {
 try {
   const entry = await api(`/api/entry?id=${encodeURIComponent(id)}`);
   state.detail = entry;
   renderDetail(entry);
  $('detail-dialog').showModal();
 } catch (error) { toast(error.message); }
}
function renderDetail(entry) {
 $('detail-content').innerHTML = `<span class="detail-language">${escapeHTML(entry.language)}</span><h2>${escapeHTML(entry.name)}</h2><p class="subtitle">${escapeHTML(entry.series)}</p><dl><dt>${t('uid')}</dt><dd class="mono">${escapeHTML(uid(entry.uid))}</dd><dt>${t('source_file')}</dt><dd class="file-path">${escapeHTML(entry.path)}</dd></dl><div class="block-heading">${t('tag_memory')} <span>${t('8_blocks_4_bytes')}</span></div><div class="blocks">${entry.blocks.map((b,i)=>`<div><span>0${i}</span><code>${escapeHTML(uid(b))}</code></div>`).join('')}</div>`;
}
function selectEntry() {
 state.selected=state.detail;
  $('write-selection').innerHTML=`<span class="detail-language">${escapeHTML(state.selected.language)}</span><h2>${escapeHTML(state.selected.name)}</h2><p>${escapeHTML(state.selected.series)}</p><code>${escapeHTML(uid(state.selected.uid))}</code>`;
 $('detail-dialog').close(); showView('write'); window.scrollTo({top:0,behavior:'smooth'});
}
function confirmation(title, description, button='Confirm') {
 $('confirm-title').textContent=title; $('confirm-description').textContent=description; $('accept-confirm').textContent=button;
 return new Promise(resolve => {
  const dialog=$('confirm-dialog');
  function finish(value) { dialog.removeEventListener('cancel', cancel); $('accept-confirm').onclick=null; $('cancel-confirm').onclick=null; dialog.close(); resolve(value); }
  function cancel(event) { event.preventDefault(); finish(false); }
  $('accept-confirm').onclick=()=>finish(true); $('cancel-confirm').onclick=()=>finish(false); dialog.addEventListener('cancel',cancel); dialog.showModal();
 });
}
function settings() { return {port:$('serial-port').value, verbose:$('verbose').checked, json:$('json-output').checked}; }
function setBusy(busy) { state.busy=busy; document.querySelectorAll('[data-operation]').forEach(el=>el.disabled=busy); $('activity-dot').hidden=!busy; }
async function runAction(action, extra={}) {
  if(state.busy) return toast(t('wait_for_the_current_operation_to_finish'));
 setBusy(true);
 let started=false;
 try {
  const result=await api('/api/run',{action,...settings(),...extra}); started=true;
    $('console-panel').hidden=false; $('console-title').textContent=t(({preview:'preview',write:'writing_to_tag',read:'checking_tag',doctor:'checking_your_setup',probe:'testing_writable_tag',index:'refreshing_collection'})[action]);
   $('console-status').textContent=t('running'); $('job-indicator').classList.add('running'); $('console-output').textContent=t('starting_operation');
  $('console-panel').scrollIntoView({behavior:'smooth',block:'nearest'});
  let job;
  for (;;) {
   try { job=await api(`/api/jobs/${result.id}`); }
    catch(error) { $('console-status').textContent=t('connection_lost_retrying'); await new Promise(r=>setTimeout(r,2000)); continue; }
    $('console-output').textContent=job.output || t('waiting_for_output');
   $('console-output').scrollTop=$('console-output').scrollHeight;
   if(job.done) break;
   await new Promise(r=>setTimeout(r,650));
  }
   $('console-status').textContent=job.code===0 ? (action==='preview'?t('preview_ready_no_hardware_touched'):t('completed')) : t('failure_exit', {code:job.code});
  $('job-indicator').classList.remove('running');
  job.time=new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); state.jobs.unshift(job); renderHistory();
  if(action==='index' && job.code===0) await loadCatalog();
  } catch(error) { toast(error.message); if(started) $('console-status').textContent=t('could_not_complete_operation'); }
 finally {setBusy(false);}
}
async function writeAction(action) {
  if(!state.selected) { toast(t('choose_a_tonie_from_the_library_first')); return showView('catalog'); }
 const retries=Number($('retries').value);
  if(!Number.isInteger(retries)||retries<1||retries>10) return toast(t('choose_between_1_and_10_retries'));
 const entry=state.selected, mode=$('write-mode').value, no_verify=$('no-verify').checked;
  const description = t('write_confirmation_description', {language:entry.language, series:entry.series, uid:uid(entry.uid), mode:$('write-mode').selectedOptions[0].textContent, verification:t(no_verify ? 'verification_disabled' : 'verification_enabled')});
  if(action==='write' && !await confirmation(t('write_confirmation_title', {name:entry.name}), description, t('write_this_tonie'))) return;
 runAction(action,{id:entry.id,mode,retries,no_verify,confirmed:action==='write'});
}
function renderHistory() {
  $('history').innerHTML=state.jobs.length ? state.jobs.map(job=>`<details class="history-item"><summary><span>${escapeHTML(job.action)} <small>${escapeHTML(job.time)}</small></span><span class="${job.code===0?'success':'failure'}">${job.code===0?t('completed'):t('failure_exit', {code:job.code})}</span></summary><pre>${escapeHTML(job.output)}</pre></details>`).join('') : `<div class="empty"><span>≋</span><h3>${t('a_fresh_start')}</h3><p>${t('your_previews_and_operations_will_appear_here')}</p></div>`;
}
try { language = localStorage.getItem('tonie-studio-language') === 'de' ? 'de' : 'en'; } catch { /* Language choice is optional. */ }
applyLanguage(language);
$('language-toggle').onclick = () => {
 language = language === 'de' ? 'en' : 'de';
 try { localStorage.setItem('tonie-studio-language', language); } catch { /* Keep the toggle usable. */ }
 applyLanguage(language);
};
document.querySelectorAll('[data-view]').forEach(el=>el.onclick=()=>showView(el.dataset.view));
window.addEventListener('hashchange',()=>showView(location.hash.slice(1)));
$('catalog-grid').onclick=event=>{const card=event.target.closest('[data-entry]');if(card)openDetail(card.dataset.entry);};
$('search').oninput=()=>{clearTimeout(filter.timer);filter.timer=setTimeout(filter,200);}; $('language').onchange=()=>{populateFilters();filter();}; $('series').onchange=filter; $('sort').onchange=filter;
$('clear-filters').onclick=resetFilters; $('empty-reset').onclick=resetFilters;
$('prev-page').onclick=()=>{state.page--;renderCatalog();}; $('next-page').onclick=()=>{state.page++;renderCatalog();};
for(const mode of ['grid','list']) $(`${mode}-view`).onclick=()=>{ $('catalog-grid').classList.toggle('list-mode',mode==='list'); for(const m of ['grid','list']) {$(`${m}-view`).classList.toggle('selected',mode===m);$(`${m}-view`).setAttribute('aria-pressed',String(mode===m));} };
 $('refresh-catalog').onclick=()=>loadCatalog().then(()=>toast(t('library_refreshed_from_the_local_catalog'))).catch(e=>toast(e.message));
$('choose-tonie').onclick=()=>showView('catalog'); $('select-detail').onclick=selectEntry; $('close-detail').onclick=()=>$('detail-dialog').close();
$('download-nfc').onclick=()=>{if(state.detail)location.href=`/api/download?id=${encodeURIComponent(state.detail.id)}`;};
$('preview-write').onclick=()=>writeAction('preview'); $('write-tag').onclick=()=>writeAction('write');
$('read-tag').onclick=()=>runAction('read'); $('run-doctor').onclick=()=>runAction('doctor'); $('rebuild-index').onclick=()=>runAction('index');
$('probe-tag').onclick=async()=>{if(await confirmation(t('test_the_tag_s_magic_uid'), t('this_writes_the_temporary_uid_e0_04_03_00_00_00_00_01_the_cli_attempts_to_restore_the_original_uid_if_it_can_read_it_first_if_the_original_uid_cannot_be_read_it_may_not_be_restorable_keep_the_tag_flat_on_the_reader'), t('run_uid_probe')))runAction('probe',{confirmed:true});};
$('copy-output').onclick=async()=>{try{await navigator.clipboard.writeText($('console-output').textContent);toast(t('output_copied'));}catch{toast(t('select_the_output_text_and_copy_it_manually'));}};
 $('serial-port').oninput=()=>{$('port-summary').textContent=$('serial-port').value || t('reader_selected_automatically');};
document.addEventListener('keydown',event=>{if(event.key==='/' && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName) && !document.querySelector('dialog[open]')){event.preventDefault();showView('catalog');$('search').focus();}});
window.addEventListener('beforeunload',event=>{if(state.busy){event.preventDefault();event.returnValue=t('an_operation_is_still_running');}});
(async()=>{showView(location.hash.slice(1));try{const config=await api('/api/config');state.token=config.token;$('serial-port').value=config.port;$('serial-port').oninput();await loadCatalog();}catch(error){$('showing').textContent=t('could_not_load_the_catalog_check_the_terminal_and_refresh');toast(error.message);}})();
