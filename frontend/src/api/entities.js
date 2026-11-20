import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:(versionId)=>api('/deliveries'+(versionId?'?bulletin_version_id='+versionId:''))};
export const bulletins={
 series:()=>api('/bulletins/series'),
 inbox:(params={})=>{const q=new URLSearchParams(Object.entries(params).filter(([,v])=>v)).toString();return api('/bulletins/inbox'+(q?'?'+q:''));},
 detail:id=>api('/bulletins/versions/'+id),
 sign:id=>api('/bulletins/versions/'+id+'/sign',{method:'POST'}),
 reject:(id,reason)=>api('/bulletins/versions/'+id+'/reject',{method:'POST',body:JSON.stringify({reason:reason??''})}),
 restore:id=>api('/bulletins/versions/'+id+'/restore'),
 correction:(report_id,reason='')=>api('/bulletins/corrections',{method:'POST',body:JSON.stringify({report_id,reason})}),
};
