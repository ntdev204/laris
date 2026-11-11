# ruff: noqa: E501  (embedded HTML/JS keeps long lines)
"""Chat web UI served by `laris app serve` (no external assets, no dependencies)."""

PAGE = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LARIS</title>
<style>
:root{--bg:#f6f5f1;--side:#efede7;--card:#fff;--ink:#1c1c1a;--mute:#6c6b65;--line:#e1dfd7;--accent:#2f5d50;--accent-ink:#fff;--user:#e8efe9;--warn:#8a5a00;--warnbg:#fff4dc;--code:#f0eee8;--err:#b3261e;--ok:#2e7d4f}
@media (prefers-color-scheme:dark){:root{--bg:#171716;--side:#1d1d1b;--card:#222220;--ink:#ecebe5;--mute:#9b9a92;--line:#33322e;--accent:#7fc4ae;--accent-ink:#10201a;--user:#26332d;--warn:#f0c674;--warnbg:#2c2615;--code:#2a2a27;--err:#f2867e;--ok:#7fd1a0}}
*{box-sizing:border-box}html,body{height:100%}body{margin:0;background:var(--bg);color:var(--ink);font:15.5px/1.6 system-ui,sans-serif;display:flex}
button{font:inherit;cursor:pointer;border:0;border-radius:8px;background:var(--accent);color:var(--accent-ink);padding:8px 14px}
button.ghost{background:transparent;color:var(--ink);border:1px solid var(--line)}button.ghost:hover{background:var(--code)}button:disabled{opacity:.5;cursor:default}
input,textarea,select{font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px;width:100%}
aside{width:272px;background:var(--side);border-right:1px solid var(--line);display:flex;flex-direction:column;padding:12px;gap:10px;flex-shrink:0}
aside h1{font-size:18px;margin:2px 4px}aside h1 small{display:block;font-weight:400;font-size:12px;color:var(--mute)}
#list{flex:1;overflow:auto;display:flex;flex-direction:column;gap:2px}
.conv{display:flex;align-items:center;gap:4px;padding:7px 10px;border-radius:8px;cursor:pointer;font-size:14px}.conv:hover,.conv.on{background:var(--code)}
.conv span{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.conv i{font-style:normal;color:var(--mute);visibility:hidden;padding:0 4px}.conv:hover i{visibility:visible}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--mute);margin-right:6px}.dot.ok{background:var(--ok)}.dot.bad{background:var(--err)}
main{flex:1;display:flex;flex-direction:column;min-width:0}
header{display:flex;align-items:center;gap:10px;padding:10px 18px;border-bottom:1px solid var(--line)}header b{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#menu{display:none}
#msgs{flex:1;overflow:auto;padding:18px}.wrap{max-width:820px;margin:0 auto}
.notice{background:var(--warnbg);color:var(--warn);border-radius:8px;padding:8px 12px;font-size:13.5px;margin-bottom:14px}
.msg{margin:14px 0;display:flex;flex-direction:column}.msg.user{align-items:flex-end}
.bubble{background:var(--user);border-radius:14px;padding:9px 14px;max-width:88%;white-space:pre-wrap;word-break:break-word}
.bot{max-width:100%;word-break:break-word}.bot p{margin:.4em 0}.bot pre{background:var(--code);padding:10px 12px;border-radius:8px;overflow:auto;font-size:13.5px}
.bot code{background:var(--code);padding:1px 5px;border-radius:4px;font-size:.92em}.bot pre code{padding:0;background:none}
.bot ul,.bot ol{margin:.4em 0;padding-left:1.4em}.bot h3,.bot h4{margin:.8em 0 .2em}
details.tool{border:1px solid var(--line);border-radius:8px;margin:6px 0;font-size:13.5px;background:var(--card)}
details.tool summary{padding:6px 10px;cursor:pointer;color:var(--mute)}details.tool pre{margin:0;padding:8px 10px;overflow:auto;max-height:260px;border-top:1px solid var(--line);font-size:12.5px;white-space:pre-wrap}
details.tool.fail summary{color:var(--err)}
.actions{margin-top:2px}.actions button{padding:2px 8px;font-size:12.5px}
.cursor::after{content:"▍";animation:b 1s steps(2) infinite;color:var(--mute)}@keyframes b{50%{opacity:0}}
#empty{text-align:center;margin-top:12vh;color:var(--mute)}#empty h2{color:var(--ink);margin:0 0 6px}
#empty .ex{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:16px}
footer{padding:10px 18px 16px}.composer{max-width:820px;margin:0 auto;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:8px 10px}
.composer textarea{border:0;background:transparent;resize:none;max-height:200px;padding:6px 4px;outline:0}
.bar{display:flex;gap:8px;align-items:center}.bar .grow{flex:1}.chips{display:flex;gap:6px;flex-wrap:wrap}.chip{background:var(--code);border-radius:999px;padding:2px 10px;font-size:13px}
.hint{text-align:center;color:var(--mute);font-size:12px;margin-top:6px}
.modal{position:fixed;inset:0;background:#0008;display:none;align-items:center;justify-content:center;padding:16px}.modal.on{display:flex}
.panel{background:var(--card);border-radius:12px;padding:18px;max-width:640px;width:100%;max-height:90vh;overflow:auto}
.panel h2{margin:0 0 10px;font-size:18px}.panel label{display:block;margin:10px 0 3px;font-size:13.5px;color:var(--mute)}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.hit{border-top:1px solid var(--line);padding:8px 0}.hit h3{margin:0;font-size:14.5px}.meta{color:var(--mute);font-size:13px}.hit p{margin:3px 0;white-space:pre-wrap;font-size:14px}mark{background:#ffe97a55;color:inherit}
table{border-collapse:collapse;margin:8px 0;font-size:13px}th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}th{background:var(--code)}blockquote{margin:8px 0;padding:4px 12px;border-left:3px solid var(--accent);color:var(--mute)}hr{border:0;border-top:1px solid var(--line);margin:12px 0}
#slash{position:absolute;bottom:100%;left:0;right:0;background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:6px;max-height:260px;overflow:auto;box-shadow:0 6px 20px #0003}
#slash div{padding:7px 12px;cursor:pointer;font-size:14px}#slash div b{color:var(--accent)}#slash div.on,#slash div:hover{background:var(--code)}#slash small{color:var(--mute);display:block;font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.composer{position:relative}.note{margin:10px 0;font-size:13px;color:var(--mute);border-left:3px solid var(--accent);padding-left:10px}
#meter{display:inline-block;width:70px;height:6px;border-radius:3px;background:var(--line);vertical-align:middle;margin:0 6px;overflow:hidden}#meter i{display:block;height:100%;background:var(--accent)}#meter.hot i{background:var(--warn)}
@media (max-width:760px){aside{position:fixed;inset:0 auto 0 0;z-index:5;transform:translateX(-100%);transition:transform .2s}aside.open{transform:none}#menu{display:inline-block}}
</style></head><body>
<aside id="side"><h1>LARIS<small>trợ lý nghiên cứu cục bộ</small></h1>
<button id="new">+ Cuộc trò chuyện mới</button><div id="list"></div>
<button class="ghost" id="bhelp">Hướng dẫn</button><a class="ghost" href="/guide" target="_blank" rel="noopener" style="text-decoration:none;padding:6px 10px">Trang hướng dẫn</a><button class="ghost" id="bskills">Skills</button><button class="ghost" id="bcorpus">Kho tài liệu</button><button class="ghost" id="bset">Cài đặt</button>
<div class="meta" id="health"><span class="dot"></span>đang kiểm tra…</div></aside>
<main><header><button class="ghost" id="menu">☰</button><b id="title">Cuộc trò chuyện mới</b></header>
<div id="msgs"><div class="wrap" id="chat"></div></div>
<footer><div class="composer"><div class="chips" id="chips"></div>
<div id="slash" hidden></div><textarea id="input" rows="1" placeholder="Hỏi về tài liệu, giao việc đọc file, trích claim… (Enter để gửi, Shift+Enter xuống dòng)"></textarea>
<div class="bar"><button class="ghost" id="attach" title="Đính kèm tệp">＋ Tệp</button><input type="file" id="file" multiple hidden accept=".txt,.md,.pdf,.png,.jpg,.jpeg,.tif,.tiff">
<span class="grow meta" id="state"></span><button id="send">Gửi</button><button id="stop" class="ghost" hidden>Dừng</button></div></div>
<div class="hint"><span id="ctx"></span> <button class="ghost" id="bcompact" style="padding:1px 8px;font-size:12px" title="Nén ngữ cảnh ngay">Nén</button></div>
<div class="hint">Bản nghiên cứu: mô hình lõi chưa được nghiệm thu. Kiểm tra nguồn trước khi dùng kết quả.</div></footer></main>

<div class="modal" id="mset"><div class="panel"><h2>Cài đặt</h2>
<div class="notice">Để trống địa chỉ API để dùng trợ lý tích hợp (quy trình viết sẵn, không có mô hình). Điền địa chỉ server mô hình (chuẩn OpenAI) để dùng mô hình thật.</div>
<label>Địa chỉ API mô hình</label><input id="s_url">
<label>Tên mô hình</label><input id="s_model"><label>Biến môi trường chứa API key (tùy chọn, không lưu khóa)</label><input id="s_key" placeholder="LARIS_API_KEY">
<label>Hướng dẫn bổ sung của bạn (không thay thế quy tắc hệ thống)</label><textarea id="s_prompt" rows="3"></textarea>
<label><input type="checkbox" id="s_learn" style="width:auto"> Lưu các lượt trả lời tốt để fine-tune sau (chỉ trên máy này, đã che thông tin nhạy cảm)</label>
<label><input type="checkbox" id="s_compact" style="width:auto"> Tự động nén ngữ cảnh khi gần đầy (khuyến nghị, mặc định bật)</label>
<div class="row"><div style="flex:1"><label>Cửa sổ ngữ cảnh (token)</label><input id="s_window" type="number" min="2048" step="1024"></div><div style="flex:1"><label>Ngưỡng nén (0.3 – 0.95)</label><input id="s_thr" type="number" min="0.3" max="0.95" step="0.05"></div></div>
<label><input type="checkbox" id="s_write" style="width:auto"> Cho phép trợ lý ghi file (vào artifacts/chat/output) và nạp tài liệu</label>
<div class="row" style="margin-top:14px"><button id="s_save">Lưu và kiểm tra kết nối</button><button class="ghost" data-close>Đóng</button><span class="meta" id="s_msg"></span></div></div></div>

<div class="modal" id="mskills"><div class="panel"><h2>Skills</h2><div class="meta" id="k_info"></div><div id="k_list"></div>
<div class="row" style="margin-top:12px"><button class="ghost" data-close>Đóng</button></div></div></div>
<div class="modal" id="mcorpus"><div class="panel"><h2>Kho tài liệu</h2><div class="meta" id="c_status"></div>
<div class="row" style="margin:10px 0"><input type="file" id="c_file" multiple accept=".txt,.md,.pdf,.png,.jpg,.jpeg,.tif,.tiff" style="flex:1"><button class="ghost" id="c_up">Nạp</button><button class="ghost" id="c_idx">Lập chỉ mục dense</button></div>
<div class="meta" id="c_msg"></div>
<form class="row" id="c_form" style="margin-top:10px"><input id="c_q" placeholder="Tìm trong kho" style="flex:1"><select id="c_mode" style="width:auto"><option value="bm25">BM25</option><option value="hybrid">Hybrid</option><option value="dense">Dense</option></select><button>Tìm</button></form>
<div id="c_out"></div><div class="row" style="margin-top:12px"><button class="ghost" data-close>Đóng</button></div></div></div>

<script>
const $=id=>document.getElementById(id);
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
async function api(path,body,method){const o={method:method||(body?'POST':'GET')};if(body!==undefined){o.headers={'Content-Type':'application/json'};o.body=JSON.stringify(body)}
const r=await fetch(path,o);const j=await r.json();if(!r.ok)throw new Error(j.error||r.statusText);return j}
let current=null,busy=false,abort=null,attachments=[];

/* ---------- markdown (DOM only, no innerHTML) ---------- */
function inline(parent,text){const re=/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g;
text.split(re).forEach(p=>{if(!p)return;let m;
if(p[0]==='`'&&p.length>1){parent.append(el('code',null,p.slice(1,-1)))}
else if(p.startsWith('**')&&p.endsWith('**')&&p.length>4){parent.append(el('strong',null,p.slice(2,-2)))}
else if((m=p.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/))){const a=el('a',null,m[1]);a.href=m[2];a.target='_blank';a.rel='noopener noreferrer';parent.append(a)}
else parent.append(document.createTextNode(p))})}
function markdown(text){const root=document.createElement('div');const lines=text.split('\n');let i=0;
while(i<lines.length){const l=lines[i];
if(l.startsWith('```')){const buf=[];i++;while(i<lines.length&&!lines[i].startsWith('```')){buf.push(lines[i]);i++}i++;const pre=el('pre');pre.append(el('code',null,buf.join('\n')));root.append(pre);continue}
const h=l.match(/^(#{1,4})\s+(.*)/);if(h){const e=el(h[1].length<=2?'h3':'h4');inline(e,h[2]);root.append(e);i++;continue}
if(/^\s*[-*]\s+/.test(l)){const ul=el('ul');while(i<lines.length&&/^\s*[-*]\s+/.test(lines[i])){const li=el('li');inline(li,lines[i].replace(/^\s*[-*]\s+/,''));ul.append(li);i++}root.append(ul);continue}
if(/^\s*\d+\.\s+/.test(l)){const ol=el('ol');while(i<lines.length&&/^\s*\d+\.\s+/.test(lines[i])){const li=el('li');inline(li,lines[i].replace(/^\s*\d+\.\s+/,''));ol.append(li);i++}root.append(ol);continue}
if(/^-{3,}\s*$/.test(l)){root.append(el('hr'));i++;continue}
if(/^>/.test(l)){const bq=el('blockquote');const bb=[];while(i<lines.length&&/^>/.test(lines[i])){bb.push(lines[i].replace(/^>\s?/,''));i++}bb.forEach((b,k)=>{if(k)bq.append(el('br'));inline(bq,b)});root.append(bq);continue}
if(/^\|/.test(l)){const rows=[];while(i<lines.length&&/^\|/.test(lines[i])){rows.push(lines[i]);i++}const t=el('table');rows.filter(r=>!/^\|[\s:|-]+\|?\s*$/.test(r)).forEach((r,k)=>{const tr=el('tr');r.replace(/^\||\|\s*$/g,'').split(/(?<!\\)\|/).forEach(c=>{const cell=el(k===0?'th':'td');inline(cell,c.trim().replace(/\\\|/g,'|'));tr.append(cell)});t.append(tr)});root.append(t);continue}
if(!l.trim()){i++;continue}
const buf=[l];i++;while(i<lines.length&&lines[i].trim()&&!/^(```|#{1,4}\s|\s*[-*]\s|\s*\d+\.\s|\||>|-{3,}\s*$)/.test(lines[i])){buf.push(lines[i]);i++}
const p=el('p');buf.forEach((b,k)=>{if(k)p.append(el('br'));inline(p,b)});root.append(p)}
return root}

/* ---------- chat rendering ---------- */
function scrollDown(){const m=$('msgs');m.scrollTop=m.scrollHeight}
function userMsg(text){const m=el('div','msg user');m.append(el('div','bubble',text));$('chat').append(m)}
function botMsg(){const m=el('div','msg');const b=el('div','bot');m.append(b);$('chat').append(m);return {root:m,box:b,text:null,raw:''}}
function toolCard(name,args){const d=el('details','tool');d.append(el('summary',null,'🔧 '+name+' '+JSON.stringify(args).slice(0,110)));d.append(el('pre',null,JSON.stringify(args,null,2)));return d}
function fillResult(card,result){const failed=result&&result.error;if(failed)card.classList.add('fail');
card.querySelector('summary').textContent=(failed?'⚠ ':'✓ ')+card.querySelector('summary').textContent.slice(2);
card.append(el('pre',null,JSON.stringify(result,null,2).slice(0,6000)))}
function setText(bot,raw){bot.raw=raw;bot.box.querySelectorAll('.txt').forEach(n=>n.remove());const t=markdown(raw);t.className='txt';bot.box.append(t);bot.text=t}
function addActions(bot){if(!bot.raw)return;const a=el('div','actions');const c=el('button','ghost','Sao chép');c.onclick=()=>{navigator.clipboard&&navigator.clipboard.writeText(bot.raw);c.textContent='Đã chép'};a.append(c);if(bot.example){[['up','👍','Câu trả lời tốt'],['down','👎','Câu trả lời chưa tốt']].forEach(([r,ic,t])=>{const b=el('button','ghost',ic);b.title=t;b.onclick=async()=>{try{await api('/api/feedback',{example_id:bot.example,rating:r});a.querySelectorAll('.rate').forEach(x=>x.disabled=true);b.textContent=ic+' ✓'}catch(e){b.title=e.message}};b.classList.add('rate');a.append(b)})}bot.root.append(a)}
function renderHistory(messages){$('chat').textContent='';const cards={};let bot=null;
messages.forEach(m=>{if(m.compacted){const d=el('details','tool');d.append(el('summary',null,'⟳ Ngữ cảnh trước đó đã được nén (xem tóm tắt)'));d.append(el('pre',null,m.content));$('chat').append(d);bot=null}
else if(m.compacted_ack||m.superseded||m.harness){}
else if(m.role==='user'){userMsg(m.content);bot=null}
else if(m.role==='assistant'){if(!bot)bot=botMsg();(m.tool_calls||[]).forEach(c=>{let a={};try{a=JSON.parse(c.function.arguments)}catch(e){}const card=toolCard(c.function.name,a);cards[c.id]=card;bot.box.append(card)});
if(m.content){setText(bot,(bot.raw?bot.raw+'\n\n':'')+m.content)}if(!(m.tool_calls||[]).length){addActions(bot);bot=null}}
else if(m.role==='tool'&&cards[m.tool_call_id]){let r={};try{r=JSON.parse(m.content)}catch(e){}fillResult(cards[m.tool_call_id],r)}});
if(!messages.length)showEmpty();scrollDown()}
function showEmpty(){const e=el('div');e.id='empty';e.append(el('h2',null,'Xin chào, tôi có thể giúp gì?'),el('div',null,'Hỏi về tài liệu trong kho, đính kèm PDF hoặc ảnh scan, hoặc giao việc cho trợ lý.'));
const ex=el('div','ex');['Tóm tắt các claim và metric trong tệp đính kèm','Kho tài liệu nói gì về BRCA1 và ung thư vú?','Đọc ảnh scan và trích dữ liệu'].forEach(t=>{const b=el('button','ghost',t);b.onclick=()=>{$('input').value=t;$('input').focus()};ex.append(b)});e.append(ex);$('chat').append(e)}

/* ---------- conversations ---------- */
async function loadList(){const rows=await api('/api/conversations');const list=$('list');list.textContent='';
rows.forEach(r=>{const d=el('div','conv'+(current&&current.id===r.id?' on':''));d.append(el('span',null,r.title));const x=el('i',null,'✕');x.title='Xóa';
x.onclick=async e=>{e.stopPropagation();if(confirm('Xóa cuộc trò chuyện này?')){await api('/api/conversations/'+r.id,undefined,'DELETE');if(current&&current.id===r.id){current=null;await open(null)}loadList()}};d.append(x);d.onclick=()=>open(r.id);list.append(d)})}
async function open(id){if(busy)return;$('side').classList.remove('open');
if(id){current=await api('/api/conversations/'+id)}else{current=null}
$('title').textContent=current?current.title:'Cuộc trò chuyện mới';renderHistory(current?current.messages:[]);showUsage(current?current.usage:null);loadList();$('input').focus()}
async function ensure(){if(!current){current=await api('/api/conversations',{})}return current}

/* ---------- send / stream ---------- */
function setBusy(b){busy=b;$('send').hidden=b;$('stop').hidden=!b;$('state').textContent=b?'Đang trả lời…':''}
async function send(){const raw=$('input').value.trim();if((!raw&&!attachments.length)||busy)return;
if(raw==='/compact'||raw.startsWith('/compact ')){$('input').value='';grow();await ensure();await doCompact(raw.slice(8).trim());return}
let text=raw;if(attachments.length){text+=(text?'\n\n':'')+attachments.map(a=>'[Tệp đính kèm: '+(a.path||a.name)+']').join('\n')}
const e=$('empty');if(e)e.remove();$('input').value='';grow();const shown=text;attachments=[];renderChips();
await ensure();userMsg(shown);const bot=botMsg();bot.box.classList.add('cursor');scrollDown();setBusy(true);abort=new AbortController();
const cards=[];let raw2='';
try{const r=await fetch('/api/conversations/'+current.id+'/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text}),signal:abort.signal});
if(!r.ok){throw new Error((await r.json()).error||r.statusText)}
const reader=r.body.getReader();const dec=new TextDecoder();let buf='';
while(true){const {value,done}=await reader.read();if(done)break;buf+=dec.decode(value,{stream:true});let k;
while((k=buf.indexOf('\n\n'))>=0){const chunk=buf.slice(0,k);buf=buf.slice(k+2);if(!chunk.startsWith('data:'))continue;const ev=JSON.parse(chunk.slice(5));
if(ev.type==='text'){raw2+=ev.delta;setText(bot,raw2)}
else if(ev.type==='tool_call'){const c=toolCard(ev.name,ev.arguments);cards.push(c);bot.box.insertBefore(c,bot.text);if(!bot.text)bot.box.append(c)}
else if(ev.type==='tool_result'){const c=cards.find(x=>!x.dataset.done&&x.querySelector('summary').textContent.includes(ev.name));if(c){c.dataset.done=1;fillResult(c,ev.result)}}
else if(ev.type==='compact'){bot.root.before(el('div','note','⟳ Đã tự động nén ngữ cảnh ('+ev.method+'): '+ev.before+' → '+ev.after+' token, '+ev.summarized+' tin nhắn được tóm tắt.'))}
else if(ev.type==='learning'){if(ev.stored)bot.example=ev.example_id}
else if(ev.type==='verify'){raw2='';setText(bot,'')}
else if(ev.type==='usage'){showUsage(ev)}
else if(ev.type==='done'){if(ev.status!=='completed'){raw2=(raw2?raw2+'\n\n':'')+'⚠ '+ev.answer;setText(bot,raw2)}else if(!bot.raw){setText(bot,ev.answer)}}
scrollDown()}}
}catch(err){if(err.name!=='AbortError'){setText(bot,'⚠ '+err.message)}else{setText(bot,(bot.raw||'')+'\n\n(đã dừng)')}}
finally{bot.box.classList.remove('cursor');addActions(bot);setBusy(false);abort=null;current=await api('/api/conversations/'+current.id);$('title').textContent=current.title;showUsage(current.usage);loadList();health()}}

/* ---------- context meter, compact, skills ---------- */
function showUsage(u){if(!u||!u.window){$('ctx').textContent='';return}const pct=Math.min(100,Math.round(100*u.tokens/u.window));
$('ctx').textContent='';const m=el('span');m.id='meter';if(pct>75)m.className='hot';const i=el('i');i.style.width=pct+'%';m.append(i);$('ctx').append(document.createTextNode('Ngữ cảnh ≈ '+u.tokens+'/'+u.window+' token'),m,document.createTextNode(pct+'%'))}
async function doCompact(instructions){if(!current){return}$('state').textContent='Đang nén ngữ cảnh…';
try{const r=await api('/api/conversations/'+current.id+'/compact',{instructions:instructions||''});const c=r.events.find(e=>e.type==='compact');
current=await api('/api/conversations/'+current.id);renderHistory(current.messages);if(c)$('chat').append(el('div','note','⟳ Đã nén ngữ cảnh ('+c.method+'): '+c.before+' → '+c.after+' token.'));else $('chat').append(el('div','note','Không có gì để nén.'));showUsage(current.usage);scrollDown()}
catch(err){alert(err.message)}finally{$('state').textContent=''}}
$('bcompact').onclick=()=>doCompact('');
let skills=[];async function loadSkills(){try{const r=await api('/api/skills');skills=r.skills;return r}catch(e){skills=[]}}
let slashIndex=0,slashItems=[];
function slashMenu(){const v=$('input').value;const menu=$('slash');
if(!v.startsWith('/')||v.includes(' ')||v.includes('\n')){menu.hidden=true;slashItems=[];return}
const q=v.slice(1).toLowerCase();slashItems=[{name:'how-to-use',description:'Hướng dẫn sử dụng chi tiết (in sẵn, không gọi mô hình)'},{name:'compact',description:'Nén ngữ cảnh ngay (tùy chọn: ghi chú ưu tiên)'},...skills].filter(s=>s.name.includes(q)).slice(0,8);
menu.textContent='';if(!slashItems.length){menu.hidden=true;return}slashIndex=Math.min(slashIndex,slashItems.length-1);
slashItems.forEach((s,i)=>{const d=el('div',i===slashIndex?'on':'');const b=el('b',null,'/'+s.name);d.append(b,el('small',null,s.description));d.onmousedown=e=>{e.preventDefault();pickSlash(i)};menu.append(d)});menu.hidden=false}
function pickSlash(i){const s=slashItems[i];if(!s)return;$('input').value='/'+s.name+' ';$('slash').hidden=true;$('input').focus();grow()}

/* ---------- composer ---------- */
function grow(){const t=$('input');t.style.height='auto';t.style.height=Math.min(t.scrollHeight,200)+'px'}
function renderChips(){const c=$('chips');c.textContent='';attachments.forEach((a,i)=>{const x=el('span','chip','📎 '+a.name+' ✕');x.style.cursor='pointer';x.onclick=()=>{attachments.splice(i,1);renderChips()};c.append(x)})}
async function toB64(f){const buf=new Uint8Array(await f.arrayBuffer());let s='';for(let i=0;i<buf.length;i+=8192)s+=String.fromCharCode.apply(null,buf.subarray(i,i+8192));return btoa(s)}
async function upload(files,ingest){const out=[];for(const f of files){out.push(await api('/api/upload',{name:f.name,data_base64:await toB64(f),ingest}))}return out}
$('attach').onclick=()=>$('file').click();
$('file').onchange=async e=>{$('state').textContent='Đang tải lên…';try{attachments.push(...await upload([...e.target.files],false))}catch(err){alert(err.message)}$('file').value='';renderChips();$('state').textContent=''};
document.addEventListener('dragover',e=>e.preventDefault());
document.addEventListener('drop',async e=>{e.preventDefault();if(e.dataTransfer.files.length){try{attachments.push(...await upload([...e.dataTransfer.files],false));renderChips()}catch(err){alert(err.message)}}});
$('input').addEventListener('input',()=>{grow();slashIndex=0;slashMenu()});
$('input').addEventListener('keydown',e=>{if(!$('slash').hidden){if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();slashIndex=(slashIndex+(e.key==='ArrowDown'?1:-1)+slashItems.length)%slashItems.length;slashMenu();return}if(e.key==='Tab'||(e.key==='Enter'&&!e.shiftKey)){e.preventDefault();pickSlash(slashIndex);return}if(e.key==='Escape'){$('slash').hidden=true;return}}
if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send()}});
$('send').onclick=send;$('stop').onclick=()=>abort&&abort.abort();
$('new').onclick=()=>open(null);$('menu').onclick=()=>$('side').classList.toggle('open');

/* ---------- modals ---------- */
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>b.closest('.modal').classList.remove('on'));
document.querySelectorAll('.modal').forEach(m=>m.onclick=e=>{if(e.target===m)m.classList.remove('on')});
$('bhelp').onclick=()=>{$('input').value='/how-to-use';send()};
$('bset').onclick=async()=>{const s=await api('/api/settings');$('s_url').value=s.base_url;$('s_model').value=s.model;$('s_key').value=s.api_key_env;$('s_prompt').value=s.extra_instructions||'';$('s_write').checked=s.allow_write;$('s_compact').checked=s.auto_compact;$('s_learn').checked=s.learning_enabled;$('s_window').value=s.context_window;$('s_thr').value=s.compact_threshold;$('s_msg').textContent='';$('mset').classList.add('on')};
$('s_save').onclick=async()=>{await api('/api/settings',{base_url:$('s_url').value.trim(),model:$('s_model').value.trim()||'laris-core',api_key_env:$('s_key').value.trim(),extra_instructions:$('s_prompt').value,allow_write:$('s_write').checked,auto_compact:$('s_compact').checked,learning_enabled:$('s_learn').checked,context_window:parseInt($('s_window').value)||32768,compact_threshold:parseFloat($('s_thr').value)||0.8});
const h=await api('/api/model-health');$('s_msg').textContent=(h.ok?'✓ ':'✗ ')+h.detail;health()};
async function health(){try{const h=await api('/api/model-health');$('health').textContent='';const d=el('span','dot '+(h.ok?'ok':'bad'));$('health').append(d,document.createTextNode(h.mode==='api'?(h.ok?'API mô hình: kết nối':'API mô hình: lỗi'):'Trợ lý tích hợp (chưa có mô hình)'));$('health').title=h.detail}catch(e){$('health').textContent=e.message}}
async function corpusStatus(){const s=await api('/api/status');$('c_status').textContent='Đoạn: '+s.passages+' · BM25: '+(s.bm25_ready?'sẵn sàng':'chưa')+' · Dense: '+(s.dense_ready?'sẵn sàng':'chưa lập chỉ mục')+' · Mô hình cục bộ: '+(s.model_configured?'đã nạp':'chưa')}
$('bskills').onclick=async()=>{const r=await loadSkills()||{skills:[],problems:[]};const info=await api('/api/instructions').catch(()=>({count:0}));
$('k_info').textContent='Chính sách nội bộ: '+(info.count?'đang áp dụng':'không có')+'. Gõ /tên-skill rồi yêu cầu để dùng.';
const l=$('k_list');l.textContent='';r.skills.forEach(k=>{const d=el('div','hit');d.append(el('h3',null,'/'+k.name),el('div','meta',k.scope+' · '+k.references+' tệp tham chiếu'),el('p',null,k.description));d.style.cursor='pointer';d.onclick=()=>{$('mskills').classList.remove('on');$('input').value='/'+k.name+' ';$('input').focus()};l.append(d)});
r.problems.forEach(p=>l.append(el('p','err',p)));$('mskills').classList.add('on')};
$('bcorpus').onclick=()=>{corpusStatus();$('mcorpus').classList.add('on')};
$('c_up').onclick=async()=>{const fs=$('c_file').files;if(!fs.length)return;$('c_msg').textContent='Đang nạp…';try{const r=await upload([...fs],true);const sk=r.map(x=>x.ingested&&x.ingested.skill).filter(Boolean);$('c_msg').textContent='Đã nạp '+r.map(x=>x.name).join(', ')+(sk.length?' · đã tạo/cập nhật skill: '+[...new Set(sk)].join(', '):'');corpusStatus()}catch(e){$('c_msg').textContent=e.message}};
$('c_idx').onclick=async()=>{$('c_msg').textContent='Đang lập chỉ mục…';try{const r=await api('/api/index',{});$('c_msg').textContent='Đã lập chỉ mục '+r.count+' đoạn';corpusStatus()}catch(e){$('c_msg').textContent=e.message}};
$('c_form').onsubmit=async e=>{e.preventDefault();const out=$('c_out');out.textContent='Đang tìm…';try{const r=await api('/api/search',{query:$('c_q').value,mode:$('c_mode').value});out.textContent='';
if(!r.hits.length)out.append(el('p','meta','Không có kết quả.'));r.hits.forEach(h=>{const d=el('div','hit');d.append(el('h3',null,h.rank+'. '+h.title),el('div','meta',h.source));d.append(el('p',null,h.text.slice(0,500)));out.append(d)})}catch(err){out.textContent=err.message}};

loadSkills();
open(location.hash.startsWith('#c=')?location.hash.slice(3):null);health();
</script></body></html>
"""


def _between(start: str, end: str) -> str:
    i = PAGE.index(start)
    return PAGE[i : PAGE.index(end, i)]


GUIDE_PAGE = (
    """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hướng dẫn sử dụng LARIS</title>
"""
    + _between("<style>", "</style>")
    + """</style>
<style>body{display:block;height:auto}main{max-width:860px;margin:0 auto;padding:20px 16px 60px}
nav{display:flex;gap:12px;align-items:center;margin-bottom:12px}nav a{color:inherit}</style></head><body>
<main><nav><a href="/">← Về trang trò chuyện</a></nav><div id="doc">Đang tải…</div></main>
<script>
"""
    + _between("function el(", "async function api(")
    + _between("function inline(", "function scrollDown(")
    + """
fetch('/api/guide').then(r=>r.json()).then(d=>{const box=document.getElementById('doc');
box.textContent='';box.append(markdown(d.markdown||''))}).catch(()=>{document.getElementById('doc').textContent='Không tải được hướng dẫn.'});
</script></body></html>
"""
)
