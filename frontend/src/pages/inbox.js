import {reports,bulletins} from '../api/entities.js';
import {download} from '../api/client.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify,fmt} from '../utils/dom.js';
import {BulletinKind,BulletinStatus} from '../constants/enums.js';

const STATUS_CLASS={pending:'st-pending',signed:'st-signed',rejected:'st-rejected'};

function deltaBlock(v){
 if(v.kind==='initial'){
  return '<div class="delta-box"><p class="hint">首发全量 · 给齐全部 <strong>'+v.anomaly_count+'</strong> 个越限日（同组、同链路、同口径）</p></div>';
 }
 const c=v.delta?.counts||{};
 const row=(op,item)=>{
  if(op==='changed')return '<tr><td>变化</td><td>'+esc(item.day)+'</td><td colspan="3">'+Object.entries(item.changes).map(([f,p])=>esc(f)+'：'+esc(fmt(p.before))+' → '+esc(fmt(p.after))).join('；')+'</td></tr>';
  const data=item.after||item.before||{};
  return '<tr><td>'+(op==='added'?'新增':'删除')+'</td><td>'+esc(item.day)+'</td><td>'+esc(data.status||'')+'</td><td>'+esc(fmt(data.ewma))+'</td><td>'+esc(fmt(data.actual))+'</td></tr>';
 };
 const items=[...(v.delta?.added||[]).map(x=>row('added',x)),...(v.delta?.removed||[]).map(x=>row('removed',x)),...(v.delta?.changed||[]).map(x=>row('changed',x))];
 return '<div class="delta-box"><div class="delta-counts"><span class="tag added">新增 '+c.added+'</span><span class="tag removed">删除 '+c.removed+'</span><span class="tag changed">变化 '+c.changed+'</span></div>'
  +'<table class="delta-table"><thead><tr><th>类型</th><th>播出日</th><th>标记</th><th>EWMA</th><th>实测</th></tr></thead><tbody>'+items.join('')+'</tbody></table></div>';
}

function caliberLine(v){
 const b=v.caliber||{};
 if(!b.channel)return '';
 return '<small class="caliber">口径：'+esc(b.channel)+' · '+(b.metric==='completion'?'实播完成率':'停播分钟')
  +' · λ='+esc(fmt(b.smoothing))+' · L='+esc(fmt(b.control_limit))+' · 基准 μ='+esc(fmt(b.mean))+' σ='+esc(fmt(b.sigma))+'</small>';
}

export async function inboxPage(statusFilter=''){
 const [series,versionsAll]=await Promise.all([bulletins.series(),bulletins.inbox()]);
 const versions=statusFilter?versionsAll.filter(v=>v.status===statusFilter):versionsAll;
 workspace.bulletinSeries=series;
 const isAdmin=session.user.role==='admin';
 const seriesName=id=>{const s=series.find(x=>x.id===id);return s?('#'+s.id+' '+s.channel+' / '+(s.metric==='completion'?'完成率':'停播')):('系列 '+id);};
 const cards=series.map(s=>'<article class="series-card"><div><strong>'+esc(s.destination)+'</strong><p>'+esc(s.channel)+' · '+(s.metric==='completion'?'实播完成率口径':'停播分钟口径')+'</p><small>底稿：'+(s.baseline_seq?('第 '+s.baseline_seq+' 份（已签收）'):'尚无签收，下一份为首发全量')+' · 共 '+s.total_versions+' 份</small></div>'
  +(s.pending_count?'<span class="status st-pending">'+s.pending_count+' 份待签收</span>':'<span class="status st-signed">无待办</span>')
  +(isAdmin?'<button class="button small" data-correction="'+s.report_id+'">并发生成更正</button>':'')+'</article>').join('');
 const list=versions.map(v=>'<article class="bulletin-item '+STATUS_CLASS[v.status]+'">'
  +'<div class="bulletin-head"><div><strong>第 '+v.seq+' 份 · '+esc(BulletinKind[v.kind]||v.kind)+'</strong><p>'+esc(seriesName(v.series_id))+' · '+esc(v.destination)+'</p></div>'
  +'<span class="status '+STATUS_CLASS[v.status]+'">'+esc(BulletinStatus[v.status]||v.status)+'</span></div>'
  +caliberLine(v)+'<p class="bulletin-summary">'+esc(v.summary)+'</p>'+deltaBlock(v)
  +'<div class="bulletin-meta"><small>生成 '+date(v.issue_at)+' · '+esc(v.created_by)+'</small>'
  +(v.signed_at?'<small>签收 '+date(v.signed_at)+' · '+esc(v.signed_by)+'</small>':'')
  +(v.rejected_at?'<small class="reject-reason">退回 '+date(v.rejected_at)+'：'+esc(v.reject_reason||'')+'</small>':'')+'</div>'
  +'<div class="bulletin-actions">'
  +'<button class="text-button" data-restore="'+v.id+'">按底稿还原整份</button>'
  +'<button class="text-button" data-archive="'+v.id+'">归档下载</button>'
  +(v.status==='pending'&&isAdmin?'<button class="button small" data-sign="'+v.id+'">签收</button><button class="button small danger" data-reject="'+v.id+'">退回</button>':'')
  +'</div></article>').join('');
 return heading('06 / INBOX','简报收件箱与底稿管理','首发送齐全部越限日，后续只发按播出日的增删改；底稿只取上一份已签收简报，退回版本不接续。','<button class="button" id="refresh-inbox">刷新 ↻</button>')
  +'<div class="inbox-layout"><section><div class="section-title"><h2>系列与底稿</h2><span>'+series.length+' 个同组/同链路/同口径系列</span></div><div class="series-list">'+(cards||'<p class="empty">尚无分发系列。</p>')+'</div>'
  +'<div class="panel filter-bar"><label>状态筛选<select id="status-filter"><option value=""'+(!statusFilter?' selected':'')+'>全部</option><option value="pending"'+(statusFilter==='pending'?' selected':'')+'>待签收</option><option value="signed"'+(statusFilter==='signed'?' selected':'')+'>已签收</option><option value="rejected"'+(statusFilter==='rejected'?' selected':'')+'>已退回</option></select></label></div></section>'
  +'<section><div class="section-title"><h2>收件箱（旧归档照常可查）</h2><span>'+versions.length+' 份</span></div><div class="bulletin-list">'+(list||'<p class="empty">暂无简报。定时计划到期或手工生成后出现在这里。</p>')+'</div></section></div>'
  +'<div id="restore-modal" class="modal hidden"></div>';
}

function openModal(html){
 const m=document.querySelector('#restore-modal');m.innerHTML=html;m.classList.remove('hidden');
 m.querySelector('[data-close]').onclick=()=>m.classList.add('hidden');
}

export function bindInbox(refresh){
 document.querySelector('#refresh-inbox').onclick=refresh;
 const filter=document.querySelector('#status-filter');
 if(filter)filter.onchange=async()=>{await inboxPage(filter.value).then(html=>{document.querySelector('main').innerHTML=html;bindInbox(refresh);});};
 document.querySelectorAll('[data-correction]').forEach(b=>b.onclick=async()=>{
  try{const v=await bulletins.correction(Number(b.dataset.correction));notify('已生成第 '+v.seq+' 份更正，进入待签收');await refresh();}
  catch(e){notify(e.message,true);}
 });
 document.querySelectorAll('[data-sign]').forEach(b=>b.onclick=async()=>{
  try{await bulletins.sign(Number(b.dataset.sign));notify('已签收，并成为该系列新底稿');await refresh();}catch(e){notify(e.message,true);}
 });
 document.querySelectorAll('[data-reject]').forEach(b=>b.onclick=async()=>{
  const reason=prompt('退回原因（退回版本不会成为底稿）：','口径待核对');
  if(reason===null)return;
  try{await bulletins.reject(Number(b.dataset.reject),reason);notify('已退回，底稿仍指向上一份签收件');await refresh();}catch(e){notify(e.message,true);}
 });
 document.querySelectorAll('[data-restore]').forEach(b=>b.onclick=async()=>{
  try{
   const full=await bulletins.restore(Number(b.dataset.restore));
   const rows=full.anomalies.map(r=>'<tr><td>'+esc(r.day)+'</td><td>'+esc(r.status)+'</td><td>'+esc(fmt(r.ewma))+'</td><td>'+esc(fmt(r.actual))+'</td><td>'+esc(fmt(r.lower))+'</td><td>'+esc(fmt(r.upper))+'</td></tr>').join('');
   openModal('<div class="modal-card"><div class="section-title"><h2>按底稿还原的整份简报</h2><button class="text-button" data-close>关闭 ✕</button></div>'
    +'<p class="hint">由第 '+full.applied_versions.map(x=>x.seq).join('、')+' 份回放得到，共 <strong>'+full.anomalies.length+'</strong> 个越限日；只读还原，不改变任何归档。</p>'
    +'<div class="table-wrap"><table><thead><tr><th>播出日</th><th>标记</th><th>EWMA</th><th>实测</th><th>下限</th><th>上限</th></tr></thead><tbody>'+rows+'</tbody></table></div></div>');
  }catch(e){notify(e.message,true);}
 });
 document.querySelectorAll('[data-archive]').forEach(b=>b.onclick=async()=>{
  try{
   const ds=await reports.deliveries(Number(b.dataset.archive));
   if(!ds.length){notify('该简报暂无落地归档文件',true);return;}
   await download(ds[0].id,'csv');
  }catch(e){notify(e.message,true);}
 });
}
