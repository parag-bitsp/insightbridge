'use strict';
const $=id=>document.getElementById(id);
const POLICY_STORAGE_KEY='productops-review-policy-v1';
const validThreshold=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=100;
function initialPolicy(){return {threshold_percent:15,applied_at:null,raw_text:'',interpretation:''};}
const state={issues:[],issue:null,tabs:{},actions:{},epoch:0,referenceEpoch:0,policy:initialPolicy(),frozenDemo:null,cachedDemos:{},analysisMode:cachedAnalysisMode(),resetNotice:''};
const isCancellation=issue=>issue.category==='cancellation'||issue.case_id.startsWith('CC-');
const names={orders:'Order details',order_events:'Order timelines',promise_history:'Delivery promises',feedback:'Customer messages',assignment_attempts:'Attempts to assign a rider',rider_availability:'Riders available nearby',label_prints:'Packing label records',packing_queues:'Orders waiting to be packed',staffing_rosters:'Staff on each shift',travel_conditions:'Delivery conditions',safety_reports:'Safety reports',supervisor_messages:'Supervisor messages',late_orders:'Orders delivered late',late_rate:'How the late-delivery rate is calculated',eligible_orders:'Orders included in the calculation',excluded_unique_orders:'Orders left out of the calculation',late_long_assignment_wait:'Orders waiting too long for a rider',late_long_packing:'Orders taking too long to pack',late_long_travel:'Orders taking too long to deliver after pickup',late_other:'Other late orders',support_contacts:'Messages sent to support',contacted_unique_orders:'Orders mentioned in customer messages',contacted_late_orders:'Late orders mentioned in customer messages',anonymous_reviews:'Reviews without a linked order',missing_original_promise:'Orders without a saved delivery promise',missing_delivery_timestamp:'Orders without a delivery time',raw_order_rows:'Order records received',scoped_unique_orders:'Orders in this review',unique_completed_orders:'Completed orders',follow_up_contacts:'Follow-up messages',source_id:'Record reference',order_id:'Order reference',store_id:'Store',received_at:'Message received',placed_at:'Order placed',original_promised_latest_at:'Promised delivery time at checkout',latest_promised_latest_at:'Latest estimated delivery time',delivered_at:'Order delivered',attempted_at:'Assignment attempted',resolved_at:'Assignment resolved',outcome:'Result',expiry_reason:'Why the attempt expired',checked_at:'Availability checked',snapshot_at:'Availability recorded',nearby_riders:'Riders nearby',eligible_nearby_riders:'Riders eligible for this order',event_type:'Event',timestamp:'Time',recorded_at:'Recorded at',promised_latest_at:'Promised delivery time',channel:'Message channel',message_kind:'Message type',language:'Language',customer_id:'Customer reference',city:'City',status:'Order status',basket_item_count:'Items in the order',packing_minutes:'Time spent packing',post_packing_assignment_wait_minutes:'Wait for a rider after packing',pickup_to_delivery_minutes:'Time from pickup to delivery'};
const natural=text=>String(text??'').replaceAll('post-packing assignment waits','waits for a rider after packing').replaceAll('post-packing assignment wait','wait for a rider after packing').replaceAll('post-packing dispatch latency','waiting time after packing').replaceAll('post-packing','after packing').replaceAll('pickup-to-delivery legs','journeys from pickup to delivery').replaceAll('eligible completed orders','completed orders with reliable timing records').replaceAll('eligible orders','orders with reliable timing records').replaceAll('scoped placement window','reviewed period').replaceAll('scoped window','reviewed period').replaceAll('scoped orders','orders in this review').replaceAll('assignment_attempts','rider-assignment records').replaceAll('rider_availability','rider-availability records').replaceAll('late_other','other late orders').replace(/\bSample orders\b/g,'The reviewed orders').replace(/\bsample orders\b/g,'the reviewed orders').replace(/\bsample assignment attempts\b/gi,'reviewed assignment attempts').replace(/sampled/gi,'reviewed').replace(/samples/gi,'reviewed records').replace(/\bsample\b/gi,'reviewed records');
Object.assign(names,{attempted_at:'Attempt made at',resolved_at:'Attempt completed at',occurred_at:'Time of event',
 kind:'Promise type',orders_waiting:'Orders waiting to be packed',observed_at:'Recorded at',
 staffed_packing_positions:'Packing positions staffed',shift_start:'Shift starts',shift_end:'Shift ends',
 attempt_number:'Attempt number',error_code:'Reported error'});
const readable=key=>names[key]||key.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
Object.assign(names,{paid_orders:'Paid orders',paid_order_lines:'Paid item lines',affected_orders:'Orders with cancelled items',cancelled_order_lines:'Cancelled item lines',cancelled_units:'Cancelled item packs',cancelled_item_value_paise:'Cancelled item value (paise)',complaint_records:'Customer messages',complained_unique_orders:'Orders mentioned in complaints',follow_up_contacts:'Follow-up messages',unaffected_orders:'Orders without cancellations',order_lines:'Items in each order',payments:'Payment records',inventory_events:'Stock movements',availability_checks:'Availability at checkout',availability_updates:'Availability updates',pick_events:'Picking records',cancellation_events:'Item cancellation records',stock_counts:'Physical stock counts',quality_inspections:'Item quality checks'});
const values={en:'English',hi_en:'Hindi and English',support_email:'Email to support',support_chat:'Chat with support',initial:'First message',follow_up:'Follow-up message',completed:'Delivered',not_collected:'Not collected',records_unavailable:'Not available'};
const plain=text=>natural(text).replaceAll('after packing assignment delay','the wait for a rider after packing').replaceAll('assignment wait','wait for a rider').replaceAll('long pickup-to-delivery','slow travel after pickup').replaceAll('long packing','slow packing').replaceAll('unique orders were contacted','different orders appeared in customer messages').replaceAll('packing throughput','how quickly orders are packed').replaceAll('queue depth','the number of orders waiting to be packed').replaceAll('staffing mismatch','a mismatch between staffing and demand').replaceAll('_',' ').replace(/\b(?:BLR|GGN)-([A-Z])\b/g,'Store $1').replace(/\b(?:DO|GG|CC)-\d+-ORD-(\d+)\b/g,(_,id)=>`order ${Number(id)}`).replace(/\bstore Store ([A-Z])\b/gi,'Store $1').replace(/\border order (\d+)\b/gi,'order $1');
const number=value=>value==null?'Not known':Number(value).toLocaleString('en-IN');
const percent=value=>value==null?'Not known':`${(value*100).toLocaleString('en-IN',{maximumFractionDigits:1})}%`;
function el(tag,attrs={},...children){const n=document.createElement(tag);for(const[k,v]of Object.entries(attrs)){if(k.startsWith('on'))n.addEventListener(k.slice(2).toLowerCase(),v);else if(v!=null)n.setAttribute(k,String(v));}for(const c of children.flat(Infinity))if(c!=null)n.append(c instanceof Node?c:document.createTextNode(String(c)));return n;}
const p=(text,cls='')=>el('p',{class:cls},plain(text));
const badge=(text,cls='')=>el('span',{class:`badge ${cls}`},text);
const button=(text,fn,cls='')=>el('button',{type:'button',class:cls,onClick:()=>safe(fn)},text);
const list=items=>el('ul',{},items.map(item=>el('li',{},plain(item))));
function field(title,value){return el('div',{class:'field'},el('span',{class:'field-title'},title),el('div',{class:'field-value'},plain(value)));}
function section(title,...children){return el('section',{class:'panel'},el('h2',{},title),...children);}
async function api(path,query,options={}){const response=await fetch(path+(query?'?'+new URLSearchParams(query):''),{cache:'no-store',...options});const data=await response.json();if(!response.ok)throw Error(data.error||'The information could not be loaded.');return data;}
async function safe(fn){try{await fn();}catch(error){const target=$('evidence-dialog').open?$('dialog-content'):$('main');target.replaceChildren(el('div',{class:'notice error',role:'alert'},el('strong',{},'This information could not be loaded'),p(error.message),button('Try again',()=>location.reload(),'quiet')));}}
function actionId(issue,rec){return `action-${issue.case_id}-${rec.id}`;}
function policyReview(issue,threshold=state.policy.threshold_percent){
 if(isCancellation(issue)){
  const action=issue.result.decision==='recommend_actions',review=!action&&!['Low','Medium'].includes(issue.result.impact.rating);
  return {outcome:action?'action_required':review?'needs_review':'no_action',threshold_percent:null,reason:action?'The evidence supports the proposed cancellation work under this rubric.':issue.result.withholding_reason||'Explain the remaining evidence gap before selecting a further action.'};
 }
 if(!validThreshold(threshold))throw Error('Enter a threshold from 0 to 100.');
 const m=issue.metrics,eligible=m.eligible_orders,late=m.late_orders;
 const result=(outcome,reason)=>({outcome,reason,threshold_percent:threshold});
 if(!Number.isInteger(eligible)||eligible<=0||!Number.isInteger(late)||late<0||late>eligible)return result('needs_review','Reliable order and late-delivery counts are needed before this review can close.');
 const rate=percent(late/eligible),scale=`${number(late)} of ${number(eligible)} orders arrived late (${rate})`;
 if(late*100>=eligible*threshold)return result('action_required',`${scale}, meeting the ${threshold}% action threshold.`);
 if(m.excluded_unique_orders!==0)return result('needs_review','Some orders could not be assessed reliably. A below-threshold rate alone cannot close this review.');
 if(!['Low','Medium'].includes(issue.result.impact.rating))return result('needs_review','Serious or uncertain customer impact requires review even below the action threshold.');
 return result('no_action',`${scale}, below the ${threshold}% action threshold. No remedial action is required under this rule. The observed delay findings remain on record.`);
}
function recommendationsFor(issue){return policyReview(issue).outcome==='no_action'?[]:issue.result.recommendations;}
function selectTab(issue,tab,updateUrl=false,focus=false){
 state.tabs[issue.case_id]=tab;
 for(const name of ['automated','actions']){
  const selected=name===tab,control=document.getElementById(`tab-${issue.case_id}-${name}`),panel=document.getElementById(`panel-${issue.case_id}-${name}`);
  if(control){control.setAttribute('aria-selected',String(selected));control.tabIndex=selected?0:-1;}
  if(panel)panel.hidden=!selected;
  if(selected&&focus)control?.focus();
 }
 if(updateUrl){const next='#'+new URLSearchParams({issue:issue.case_id,view:tab,...(tab==='actions'&&state.actions[issue.case_id]?{recommendation:state.actions[issue.case_id]}:{})}).toString();if(location.hash!==next)history.pushState(null,'',location.pathname+location.search+next);}
}
function selectAction(issue,rec,updateUrl=false){
 state.actions[issue.case_id]=rec.id;
 for(const item of recommendationsFor(issue)){
  const selected=item.id===rec.id,view=$(actionId(issue,item)),control=$('choose-'+actionId(issue,item));
  if(view)view.hidden=!selected;
  control?.setAttribute('aria-pressed',String(selected));
 }
 if(updateUrl)selectTab(issue,'actions',true);
}
function decisionKey(issue,rec){return `productops-decision-v1:${issue.case_id}:${issue.run_id}:${rec.id}`+(state.policy.threshold_percent===15?'':`:policy-${state.policy.threshold_percent}`);}
function savedDecision(issue,rec){try{const v=JSON.parse(localStorage.getItem(decisionKey(issue,rec)));return v&&['Proceed','Defer','Reject'].includes(v.decision)?v:null;}catch{return null;}}
const priorityOrder={Urgent:0,High:1,Moderate:2,Low:3};
function orderedRecommendations(issue){return [...recommendationsFor(issue)].sort((a,b)=>(priorityOrder[savedDecision(issue,a)?.priority||a.execution_priority]??4)-(priorityOrder[savedDecision(issue,b)?.priority||b.execution_priority]??4));}
function metric(value,label,ref,issue){return el('div',{class:'metric'},el('strong',{},value),button(label,()=>citation(issue,ref)));}
function evidenceLinks(issue,values){return values.length?el('div',{class:'refs'},button(values.some(v=>v.startsWith('feedback:'))?'Read the customer messages':'Inspect the supporting evidence',()=>supportingEvidence(issue,values),'link-text')):p('No supporting records were cited for this explanation.','small muted');}
async function supportingEvidence(issue,values){
 const epoch=++state.referenceEpoch;openDialog('Evidence behind this finding');$('dialog-content').replaceChildren(p('Loading the supporting records…','muted'));
 const records=await Promise.all([...new Set(values)].map(ref=>api(`/api/cases/${issue.case_id}/citation`,{ref}).then(value=>({ref,...value}))));
 if(epoch!==state.referenceEpoch)return;const target=$('dialog-content');target.replaceChildren(p(scopeLine(issue),'small muted'));
 for(const {ref,data} of records){const[kind,key]=ref.split(':');
  if(kind==='metric')target.append(field(readable(key),key==='late_rate'?percent(data.value):number(data.value)));
  else if(kind==='source_status')target.append(field(readable(key),data.status==='available'?'Records available':'Records not available for this period'));
  else if(kind==='observation')target.append(el('div',{class:'source-record'},el('h3',{},'Order timeline'),...Object.entries(data.stages).map(([stage,value])=>field(readable(stage),value==null?'Not recorded':`${number(value)} minutes`)),button('Inspect this order',()=>citation(issue,ref),'quiet')));
  else target.append(el('h3',{},readable(kind)),...data.records.map(record=>recordView(record)));
 }
 target.append(button('Browse the supporting records',()=>library(issue),'quiet'));
}
function dateRange(scope){const f=date=>new Date(date+'T12:00:00+05:30').toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric',timeZone:'Asia/Kolkata'});return `${f(scope.placement_date_start)} to ${f(scope.placement_date_end_inclusive)}`;}
function scopeLine(issue){return plain(`${issue.scope.store_ids.join(', ')} · ${dateRange(issue.scope)} · ${issue.scope.placement_time_start_inclusive.slice(0,5)}–${issue.scope.placement_time_end_exclusive.slice(0,5)} IST`);}
function compactTitle(issue){return plain(`${isCancellation(issue)?'Item cancellations':'Delivery delays'} at ${issue.scope.store_ids.join(', ')}`);}
function workspaceView(withInbox=false){
 document.body.classList.remove('home-view');
 document.body.classList.toggle('browse-view',!withInbox);
 document.querySelector('.app-layout').classList.toggle('landing-layout',!withInbox);
 $('sidebar').hidden=!withInbox;
 $('library').hidden=!withInbox;
}
const ANALYSIS_MODE_KEY='insightbridge-cached-analysis-mode-v2';
function cachedAnalysisMode(){try{return localStorage.getItem('insightbridge-cached-analysis-mode-v2')==='latency'?'latency':'astra';}catch{return 'astra';}}
async function cachedDemo(mode=state.analysisMode){
 if(!state.cachedDemos[mode])state.cachedDemos[mode]=await api('/api/inbox',{analysis_mode:mode});
 return state.cachedDemos[mode];
}
function rubricDocument(text){
 const document=el('article',{class:'rubric-document'});
 const headings=new Map([
  ['Decision rules','h3'],['Delayed deliveries','h4'],['Post-payment item cancellations','h4'],
  ['1. Context isolation','h3'],['2. Evaluation','h3'],['3. Success criteria','h3'],
  ['Flexibility versus reliability','h3'],['1. Decision rules','h3'],
  ['1.1 Delayed deliveries','h4'],['1.2 Post-payment item cancellations','h4'],
  ['2. Context isolation','h3'],['3. Evaluation','h3'],['4. Success criteria','h3'],
  ['5. Model behaviour guidelines','h3'],['6. Flexibility versus reliability','h3'],
  ['5.1 Decide what work is necessary','h4'],['5.2 Impact and execution priority','h4'],
  ['5.3 Examples of better recommendations','h4'],['5.4 Final writing check','h4'],
  ['Combine related work','h4'],['Use established facts','h4'],['Close an explained case','h4'],
  ['Match priority to harm','h4'],['Use precise, simple language','h4'],
  ['6. Roles and responsibilities','h3'],['7. Flexibility versus reliability','h3'],
  ['8. AI output evaluation rubric','h3'],['8.1 Scoring','h4'],
  ['8.2 Critical failures','h4'],['8.3 Anchor examples','h4']]);
 let paragraph=[],bullet=false,roleLines=null,scoreLines=null;
 function evaluationRubric(){
  if(scoreLines===null)return;
  const text=scoreLines.join(' ').replace(/\s+/g,' '),first=text.indexOf('Evidence and factual accuracy');
  if(first>0)document.append(el('p',{},text.slice(0,first).replace(/Criterion\s+Weight\s+Score 1 \(Poor\)\s+Score 3 \(Satisfactory\)\s+Score 5 \(Excellent\)/,'')));
  const criteria=['Evidence and factual accuracy','Decision quality','Recommendation usefulness','Clarity and brevity','Scope and authority'];
  for(const [index,criterion] of criteria.entries()){
   const start=text.indexOf(criterion),end=index+1<criteria.length?text.indexOf(criteria[index+1]):text.length;
   const body=text.slice(start+criterion.length,end).trim();
   const anchors=body.match(/^(\d+%)\s+Poor:\s*(.*?)\s+Satisfactory:\s*(.*?)\s+Excellent:\s*(.*)$/);
   if(!anchors){document.append(el('p',{},criterion+' '+body));continue;}
   document.append(el('section',{class:'rubric-score-criterion'},el('h4',{},criterion+' ('+anchors[1]+')'),
    el('dl',{},...['1 - Poor','3 - Satisfactory','5 - Excellent'].map((label,i)=>[el('dt',{},label),el('dd',{},anchors[i+2])]))));
  }
  scoreLines=null;
 }
 function roleMatrix(){
  if(roleLines===null)return;
  const text=roleLines.join(' ').replace(/\s+/g,' '),[matrix,assignment]=text.split('Assignment rules:');
  const roles=['Product owner','Store operations','Dispatch operations','Inventory and checkout engineering','Quality operations','Operations analytics'];
  const rows=roles.map((role,index)=>{
   const start=matrix.indexOf(role),end=index+1<roles.length?matrix.indexOf(roles[index+1]):matrix.length;
   const [responsibility,example]=matrix.slice(start+role.length,end).trim().split('Example:');
   return el('tr',{},el('th',{scope:'row'},role),el('td',{'data-label':'Responsibility'},responsibility.trim()),el('td',{'data-label':'Example'},example?.trim()||''));
  });
  document.append(el('table',{class:'rubric-role-matrix'},el('caption',{class:'small muted'},'Sample ownership for this demo'),
   el('thead',{},el('tr',{},...['Role','Responsibility','Typical example'].map(title=>el('th',{scope:'col'},title)))),el('tbody',{},rows)));
  if(assignment)document.append(el('p',{},el('strong',{},'Assignment rules: '),assignment.trim()));
  roleLines=null;
 }
 function flush(){
  if(!paragraph.length)return;
  if(bullet){
   const list=document.lastElementChild?.tagName==='UL'?document.lastElementChild:el('ul',{});
   list.append(el('li',{},paragraph.join(' ')));if(!list.parentNode)document.append(list);
  }else document.append(el('p',{},paragraph.join(' ')));
  paragraph=[];bullet=false;
 }
 for(const raw of String(text||'').split(/\r?\n/)){
  const line=raw.trim(),heading=line.replace(/:$/,'');
  if(!line){flush();continue;}
  if(/^\d+$/.test(line))continue;
  if(scoreLines!==null){
   if(!headings.has(heading)){scoreLines.push(line);continue;}
   evaluationRubric();
  }
  if(roleLines!==null){
   if(!headings.has(heading)&&!/^Owner decision\s*:/.test(line)){roleLines.push(line);continue;}
   roleMatrix();
  }
  if(line==='InsightBridge'){flush();document.append(el('h2',{class:'rubric-document-title'},line));}
  else if(line==='Decision rubric and demo policy'||line==='AI Decision and Evaluation Framework'){flush();document.append(el('p',{class:'rubric-subtitle'},line));}
  else if(/^Demo draft\s*\|/.test(line)){flush();document.append(el('p',{class:'rubric-meta'},line));}
  else if(headings.has(heading)){flush();document.append(el(headings.get(heading),{},heading));if(heading==='6. Roles and responsibilities')roleLines=[];if(heading==='8. AI output evaluation rubric')scoreLines=[];}
  else if(/^Owner decision\s*:/.test(line)){flush();document.append(el('p',{class:'rubric-owner-decision'},line));}
  else if(/^-\s/.test(line)){flush();bullet=true;paragraph.push(line.replace(/^-\s+/,''));}
  else if(/^(Poor|Satisfactory|Excellent|Avoid|Prefer):/.test(line)){flush();paragraph.push(line);}
  else paragraph.push(line);
 }
 flush();roleMatrix();evaluationRubric();
 return document;
}
function policyControls(){
 const viewRubric=el('a',{href:'#rubric','aria-haspopup':'dialog',onClick:async event=>{
  event.preventDefault();
  $('rubric-content').replaceChildren(el('p',{},'Loading the AI framework...'));
  $('rubric-dialog').showModal();
  $('rubric-content').scrollTop=0;
  try{
   const rubric=await api('/api/rubric/default');
   $('rubric-content').replaceChildren(rubricDocument(rubric.text));
   $('rubric-content').scrollTop=0;
  }catch(error){$('rubric-content').replaceChildren(el('p',{},`Could not load the AI framework. ${error.message}`));}
 }},'View AI framework');
 const status=el('p',{class:'small muted policy-feedback',role:'status'});
 let astra,full;
 async function load(mode){
  const epoch=++state.epoch;astra.disabled=true;full.disabled=true;
  try{
   const data=await cachedDemo(mode);if(epoch!==state.epoch)return;
   useFrozenDemo(data);state.actions={};state.tabs={};state.issue=null;
   try{localStorage.setItem(ANALYSIS_MODE_KEY,mode);}catch{}
   location.hash='view=issues';
  }catch(error){if(epoch===state.epoch)status.textContent=`Could not load cached analysis. ${error.message}`;}
  finally{astra.disabled=false;full.disabled=false;}
 }
 full=button('GPT-5.4',()=>load('latency'));
 astra=button('GPT-6 Astra',()=>load('astra'),'primary');
 return el('section',{class:'policy-settings saved-analysis-card','aria-labelledby':'policy-heading'},
  el('div',{class:'saved-analysis-controls'},el('div',{class:'saved-model-buttons'},astra,full),
   el('p',{id:'policy-heading',class:'small muted saved-results-caption'},'Compare results saved from the last run'),
   el('div',{class:'saved-analysis-links'},viewRubric,el('a',{href:'#view=evidence'},'Customer issues')),status));
}
function useFrozenDemo(data){
 state.frozenDemo=data;state.issues=data.issues;if(data.cache_mode)state.analysisMode=data.cache_mode;
 state.policy={...initialPolicy(),threshold_percent:data.policy.threshold_percent,raw_text:data.policy.raw_text,rubric_sha256:data.policy.rubric.sha256};
}
function resetDemo(){
 ++state.epoch;++state.referenceEpoch;
 for(const key of Object.keys(localStorage))if(key===POLICY_STORAGE_KEY||key.startsWith('productops-decision-v1:'))localStorage.removeItem(key);
 state.policy=initialPolicy();state.issues=[];state.issue=null;state.tabs={};state.actions={};state.resetNotice='Demo reset. Saved decisions have been cleared; frozen analysis is unchanged.';if(state.frozenDemo)useFrozenDemo(state.frozenDemo);
 if($('evidence-dialog').open)$('evidence-dialog').close();$('dialog-content').replaceChildren();
 if(location.hash!=='#home')history.pushState(null,'',location.pathname+location.search+'#home');
 home();$('main').focus({preventScroll:true});document.querySelector('.workspace').scrollTo(0,0);window.scrollTo(0,0);
}
function home(){
 workspaceView();
 document.body.classList.add('home-view');
 const card=(title,description,link,label)=>el('a',{class:'home-card',href:link},el('h2',{},title),p(description),el('span',{class:'home-card-link'},label));
 $('main').replaceChildren(el('section',{class:'home-page','aria-labelledby':'home-title'},
   el('div',{class:'home-intro'},el('h1',{id:'home-title'},'Your InsightBridge workspace'),p('Analyze customer support tickets and feedback to uncover hidden product opportunities.')),
  policyControls(),
  el('nav',{class:'home-cards','aria-label':'Workspace areas'},
   card('Issues and next action','Understand each issue, review the findings, and choose the next action.','#view=issues','Open the inbox'),
   card('JIRA tickets','View tickets prepared from the recommendations you have confirmed.','#view=jira','View tickets'),
   card('Run trace & cost','Inspect saved model calls, token usage and estimated cost for the frozen analysis.','#view=trace','View saved traces'))));
}
async function evidenceHome(epoch){
 const results=el('div',{class:'customer-tickets','aria-live':'polite'},p('Loading customer tickets…','loading'));
 $('main').replaceChildren(el('section',{class:'reference-page'},
  el('a',{href:'#home',class:'back-link'},'Back to home'),el('h1',{},'Customer issues'),
   p('Fixed synthetic customer complaints, newest first. Complaint counts differ from the number of orders reviewed in an investigation.'),results));
 // Fixed development capabilities, independent of model recommendation eligibility.
 const sources=[...['GG-01','GG-02','GG-03','GG-04'].map(caseId=>({caseId,category:'Delayed delivery',path:`/api/cases/${caseId}/evidence`,query:{source:'feedback'}})),
  ...['CC-01','CC-02','CC-03'].map(caseId=>({caseId,category:'Item cancellation',path:`/api/library/cancellations/${caseId}`,query:{}}))];
 const pages=await Promise.all(sources.map(async({caseId,category,path,query})=>{
  const records=[];let offset=0;
  do{
   const data=await api(path,{...query,offset});
   if(data.status!=='available')throw Error('Customer tickets could not be loaded for every store.');
   records.push(...data.records.map(record=>({record,caseId,category,itemLabel:data.item_label,copies:data.source_multiplicities[record.source_id]})));
   offset=data.next_offset;
  }while(offset!=null);
  return records;
 })).then(records=>({records:records.flat()}),error=>({error}));
 if(epoch!==state.epoch)return;
 if(pages.error)throw pages.error;
 const tickets=pages.records.sort((a,b)=>Date.parse(b.record.received_at)-Date.parse(a.record.received_at)||a.record.source_id.localeCompare(b.record.source_id));
  const count=p('','ticket-count small muted'),records=el('div',{});
  const filters=['All','Delayed delivery','Item cancellation'].map(category=>{
   const total=category==='All'?tickets.length:tickets.filter(ticket=>ticket.category===category).length;
   const control=button(`${category} (${total})`,()=>render(category));
   control.setAttribute('aria-pressed',String(category==='All'));
   return {category,control};
  });
  results.replaceChildren(el('div',{class:'row-start',role:'group','aria-label':'Scenario'},...filters.map(filter=>filter.control)),count,records);
  function render(category){
   const selected=category==='All'?tickets:tickets.filter(ticket=>ticket.category===category);
   for(const filter of filters){const active=filter.category===category;filter.control.setAttribute('aria-pressed',String(active));filter.control.classList.toggle('primary',active);}
   count.textContent=`Customer complaints: ${selected.length} of ${tickets.length}${category==='All'?'':` · ${category}`}.`;
   records.replaceChildren(...selected.map(({record,copies,caseId,category,itemLabel})=>el('article',{class:'customer-ticket','data-record-ref':record.source_id,'data-case-id':caseId},
   el('div',{class:'ticket-meta'},el('strong',{},plain(record.store_id)),
    el('span',{class:'badge'},category),itemLabel?el('span',{},itemLabel):null,
    el('time',{datetime:record.received_at},new Date(record.received_at).toLocaleString('en-IN',{day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit',timeZone:'Asia/Kolkata'})+' IST'),
    el('span',{},values[record.channel]||readable(record.channel)),
    record.order_id?el('span',{},plain(record.order_id)):null),
   el('blockquote',{},record.text),
   el('details',{},el('summary',{},'View original ticket details'),rowList(record),copies>1?p(`${copies} copies were imported; shown once.`,'small muted'):null))),
   !selected.length?p('No customer complaints are available.','empty'):null);
  }
  render('All');
}
function confirmedTickets(){
 const tickets=[];
 for(const key of Object.keys(localStorage)){
  if(!key.startsWith('productops-decision-v1:'))continue;
  try{const value=JSON.parse(localStorage.getItem(key)),ticket=value?.ticket;
   if(value?.decision==='Proceed'&&ticket?.schema_version===1&&typeof ticket.id==='string'&&typeof ticket.title==='string'&&Array.isArray(ticket.evidence)&&Array.isArray(ticket.evaluation_measures)&&Array.isArray(ticket.guardrails))tickets.push(ticket);
  }catch{/* Ignore unreadable records without hiding other tickets. */}
 }
 return tickets.sort((a,b)=>b.decision_recorded_at.localeCompare(a.decision_recorded_at));
}
function jiraTickets(selectedId){
 workspaceView();
 const tickets=confirmedTickets();
 const rows=tickets.map(ticket=>el('tr',{'data-ticket-id':ticket.id},
  el('td',{},el('a',{href:`#view=jira&ticket=${encodeURIComponent(ticket.id)}`,'aria-haspopup':'dialog'},plain(ticket.title)),p(ticket.store,'small muted')),
  el('td',{'data-label':'Owner'},plain(ticket.owner)),
  el('td',{'data-label':'Priority'},badge(ticket.priority)),
  el('td',{'data-label':'Status'},'To do')));
 $('main').replaceChildren(el('section',{class:'reference-page jira-page'},
  el('a',{href:'#home',class:'back-link'},'Back to home'),el('h1',{},'JIRA tickets'),
  p('Saved in this browser. Not sent to Jira.','small muted'),
  tickets.length?el('table',{class:'jira-ticket-list'},el('caption',{},`${tickets.length} confirmed ${tickets.length===1?'ticket':'tickets'}. Select a ticket to view details.`),
   el('thead',{},el('tr',{},...['Ticket','Owner','Priority','Status'].map(title=>el('th',{scope:'col'},title)))),el('tbody',{},rows)):
   el('div',{class:'empty'},p('No confirmed recommendations yet.'),el('a',{href:'#view=issues',class:'back-link'},'Review recommendations'))));
 const selected=tickets.find(ticket=>ticket.id===selectedId);
 if(selected){
  $('ticket-dialog-content').replaceChildren(ticketDetails(selected));
  if(!$('ticket-dialog').open)$('ticket-dialog').showModal();
  $('ticket-dialog-content').scrollTop=0;
 }else if($('ticket-dialog').open)$('ticket-dialog').close();
}
function ticketDetails(ticket){
 return el('article',{class:'jira-ticket','aria-label':'Ticket: '+plain(ticket.title)},
   el('h2',{},plain(ticket.title)),p(ticket.store,'small muted'),
   el('div',{class:'ticket-fields'},field('Issue type','Task'),field('Status','To do'),field('Owner',ticket.owner),field('Priority',ticket.priority)),
   field('Problem',ticket.issue),field('Why this action',ticket.rationale),field('Work scope',ticket.scope),
   field('Expected outcome',ticket.expected_outcome),
   el('h3',{},'Acceptance criteria'),list(ticket.evaluation_measures.map(t=>names[t]||natural(t))),
   field('Boundaries',ticket.authority),el('h3',{},'Limits to respect'),list(ticket.guardrails),
   ticket.note?field('Owner note',ticket.note):null,
   el('details',{class:'more-evidence'},el('summary',{},'Supporting evidence and review details'),
    ...ticket.evidence.map(f=>p(f.text)),field('Applied rubric',ticket.review_category==='cancellation'?'Evidence-backed cancellation review; no numerical threshold.':`Action required at ${ticket.policy_threshold_percent}% late deliveries.`),ticket.rubric_sha256?field('Rubric version',ticket.rubric_sha256):null,field('Confirmed',time(ticket.decision_recorded_at)),field('Review reference',ticket.source_run),field('Recommendation reference',ticket.recommendation_id)),
   p('Not sent to Jira','small muted'));
}
$('close-ticket').addEventListener('click',()=>$('ticket-dialog').close());
$('ticket-dialog').addEventListener('close',()=>{
 const params=new URLSearchParams(location.hash.slice(1)),ticket=params.get('ticket');
 if(params.get('view')==='jira'&&ticket){
  params.delete('ticket');history.replaceState(null,'','#'+params);
  [...document.querySelectorAll('.jira-ticket-list tr[data-ticket-id]')].find(row=>row.dataset.ticketId===ticket)?.querySelector('a')?.focus();
 }
});
async function route(){
 const epoch=++state.epoch;
 const params=new URLSearchParams(location.hash.slice(1));
 const reference=params.get('view');
 if(reference!=='jira'&&$('ticket-dialog').open)$('ticket-dialog').close();
 if(!params.get('issue')&&!params.get('case')&&reference!=='issues'&&reference!=='evidence'){
  if(reference==='jira')jiraTickets(params.get('ticket'));else if(reference==='trace'){workspaceView();await traceHome(epoch,params.get('run'));if(epoch!==state.epoch)return;}else {if(!state.frozenDemo){const data=await cachedDemo();if(epoch!==state.epoch)return;useFrozenDemo(data);}home();}
  $('main').focus({preventScroll:true});document.querySelector('.workspace').scrollTo(0,0);window.scrollTo(0,0);return;
 }
 workspaceView(reference!=='evidence');
 if(reference==='evidence'){await evidenceHome(epoch);if(epoch!==state.epoch)return;$('main').focus({preventScroll:true});document.querySelector('.workspace').scrollTo(0,0);window.scrollTo(0,0);return;}
 if(!state.issues.length){
  $('main').replaceChildren(p('Preparing your inbox…','loading'));
  const data=await cachedDemo();
  if(epoch!==state.epoch)return;useFrozenDemo(data);
 }
 if(epoch!==state.epoch)return;
 const issue=state.issues.find(i=>i.case_id===(params.get('issue')||params.get('case')));
 const rec=issue?recommendationsFor(issue).find(r=>r.id===params.get('recommendation'))||(params.get('tab')==='recommendations'?recommendationsFor(issue)[0]:null):null;
 if(rec)state.actions[issue.case_id]=rec.id;
 for(const item of state.issues)state.tabs[item.case_id]=item===issue&&(rec||params.get('view')==='actions')?'actions':'automated';
 state.issue=issue||state.issues[0]||null;inbox();
 const inline=issue&&rec?document.getElementById(actionId(issue,rec)):null;
 if(inline){inline.scrollIntoView({block:'start'});inline.focus({preventScroll:true});}
 else{$('main').focus({preventScroll:true});document.querySelector('.workspace').scrollTo(0,0);window.scrollTo(0,0);}
}
function inbox(){
 const main=$('main');
 renderSidebar();
 main.replaceChildren();
 if(!state.issues.length){main.append(section('Nothing needs your decision yet',p('Recommendations will appear here once their figures, evidence and action requirements have been checked.')));return;}
 for(const issue of [state.issue]){
  const m=issue.metrics,r=issue.result,cancellation=isCancellation(issue),facts=r.findings.filter(f=>f.kind!=='hypothesis');
  const details=facts.filter(f=>f.evidence_refs.some(ref=>!ref.startsWith('metric:')));
  const summaryMetric=(value,label)=>el('div',{class:'metric'},el('strong',{},value),el('span',{},label));
  const assessment=policyReview(issue),noAction=assessment.outcome==='no_action',recommendations=orderedRecommendations(issue);
  const article=el('article',{class:'issue-brief'},el('div',{class:'row'},el('h1',{class:'issue-title'},issue.title||'Delayed deliveries'),badge(`${r.impact.rating} customer impact`)),p(`${issue.scope.city||''} · ${scopeLine(issue)}`,'small muted'));
  const originalThreshold=issue.triage_policy?.threshold_percent??15;
  article.append(el('div',{class:'policy-context'},el('span',{},cancellation?'Item cancellations are reviewed using the available records. No numerical threshold applies.':`Action is required at ${assessment.threshold_percent}% late deliveries.`),!cancellation&&assessment.threshold_percent!==originalThreshold?el('span',{class:'policy-origin'},`Findings from the original ${originalThreshold}% review are unchanged.`):null));
  const description=el('div',{class:'issue-description'},p(r.issue_summary,'issue-summary'),
   el('div',{class:'metrics issue-numbers'},...(cancellation?[summaryMetric(number(m.affected_orders),`of ${number(m.paid_orders)} paid orders affected`),summaryMetric(number(m.cancelled_units),'Item packs cancelled'),summaryMetric(number(m.complaint_records),'Customer messages')]:[summaryMetric(percent(m.late_rate),`${number(m.late_orders)} of ${number(m.eligible_orders)} orders arrived late`)])),
   m.excluded_unique_orders?p(`${number(m.excluded_unique_orders)} orders could not be included because delivery promises or delivery times were missing.`,'small muted'):null,
   el('h3',{},'Customer impact'),p(r.impact.rationale),
   el('div',{class:`policy-line ${noAction?'closed':''}`},el('strong',{},noAction?'No further work needed':assessment.outcome==='action_required'?'Remedial actions proposed':'Further review needed')));
  const automated=el('section',{class:'inbox-section automated-section'},description,
   el('h3',{},'What the records show'),...details.map(f=>el('article',{class:'finding'},p(f.text))));
  if(r.gaps.length)automated.append(el('h3',{},'What is still unknown'),list(r.gaps));
  if(r.alternatives.length)automated.append(el('h3',{},'Other possible explanations'),list(r.alternatives.map(a=>a.explanation)));
  if(noAction)automated.append(field('Why this review is closed',assessment.reason));
  automated.append(button('View supporting records',()=>library(issue),'quiet'));
  const actions=el('section',{class:'inbox-section lead-section','aria-label':'Recommended actions'});
  if(recommendations.length>1){
   actions.append(el('h3',{class:'proposed-heading'},'Proposed work'),p('Choose a recommendation to read its reason and decide.','small muted'),el('nav',{class:'action-choices','aria-label':'Choose a recommendation'},recommendations.map(rec=>el('button',{type:'button',id:'choose-'+actionId(issue,rec),class:'action-choice','aria-controls':actionId(issue,rec),'aria-pressed':false,onClick:()=>selectAction(issue,rec,true)},el('span',{class:'row'},el('strong',{},({corrective_change:'Correct the observed failure',diagnostic:cancellation?'Investigate the cancellation':'Investigate the delay',source_quality:'Gather more context',pilot_preparation:'Prepare a limited trial'}[rec.action_type]||'Review the proposed work')),badge(rec.execution_priority+' priority')),el('span',{class:'action-question'},plain(rec.remaining_question))))));
  }
  if(!recommendations.length)actions.append(el('div',{class:'no-action'},el('h3',{},noAction?'No action required':'Further investigation needed'),p(noAction?assessment.reason:assessment.reason),button('Read the issue description',()=>selectTab(issue,'automated',true,true),'quiet')));
  else if(assessment.outcome==='needs_review')actions.prepend(p(assessment.reason,'notice neutral'));
  const tablist=el('div',{class:'tabs issue-tabs',role:'tablist','aria-label':'Issue information'});
  for(const [name,label] of [['automated','Issue description'],['actions','Remedial actions']]){
   tablist.append(el('button',{type:'button',class:'tab',role:'tab',id:`tab-${issue.case_id}-${name}`,'aria-controls':`panel-${issue.case_id}-${name}`,'aria-selected':false,tabindex:-1,onClick:()=>selectTab(issue,name,true),onKeyDown:event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();const next=event.key==='Home'?'automated':event.key==='End'?'actions':name==='automated'?'actions':'automated';selectTab(issue,next,true,true);
   }},label));
  }
  automated.id=`panel-${issue.case_id}-automated`;automated.setAttribute('role','tabpanel');automated.setAttribute('aria-labelledby',`tab-${issue.case_id}-automated`);
  const actionPanel=el('div',{class:'actions-panel',id:`panel-${issue.case_id}-actions`,role:'tabpanel','aria-labelledby':`tab-${issue.case_id}-actions`},actions);
  article.append(tablist,automated,actionPanel);
  for(const rec of recommendations){
   const inline=el('section',{class:'inline-review',id:actionId(issue,rec),tabindex:-1,'aria-label':'Recommendation and decision'});
   actions.append(inline);review(issue,rec,inline);
  }
  main.append(article);
  if(recommendations.length)selectAction(issue,recommendations.find(rec=>rec.id===state.actions[issue.case_id])||recommendations[0]);
  selectTab(issue,state.tabs[issue.case_id]||'automated');
 }
}
function renderSidebar(){
 const sidebar=$('sidebar');sidebar.replaceChildren(el('div',{class:'inbox-heading'},el('h2',{},'Inbox'),el('span',{class:'inbox-count'},state.issues.length)),el('div',{class:'category-current'},state.issues.some(isCancellation)?'Customer issues':'Delayed deliveries'),p('Gurgaon · Saved analysis','sidebar-label'));
 const nav=el('nav',{'aria-label':'Issue inbox'});
 for(const issue of state.issues){
  const assessment=policyReview(issue),recommendations=recommendationsFor(issue),pending=recommendations.filter(r=>!savedDecision(issue,r)||savedDecision(issue,r).decision==='Defer').length;
  const complete=assessment.outcome==='no_action';
  const stages=[['late_long_assignment_wait','Rider assignment is taking too long'],['late_long_packing','Packing is taking too long'],['late_long_travel','Delivery after pickup is taking too long']].sort((a,b)=>issue.metrics[b[0]]-issue.metrics[a[0]]);
  const subject=isCancellation(issue)?`${issue.item_label||'Item cancellations'}${complete?' — reviewed':''}`:complete?'Below threshold — no action required':issue.metrics[stages[0][0]]?stages[0][1]:'Delivery delays need review';
  const day=new Date(issue.scope.placement_date_end_inclusive+'T12:00:00+05:30').toLocaleDateString('en-IN',{day:'numeric',month:'short',timeZone:'Asia/Kolkata'});
  const link=el('a',{class:`store-link inbox-message ${!complete&&(pending||!recommendations.length)?'needs-action':''}`,href:'#'+new URLSearchParams({issue:issue.case_id,view:'automated'}),'aria-current':state.issue===issue?'page':null},
   el('span',{class:'message-from'},el('span',{},plain(issue.scope.store_ids.join(', '))),el('small',{class:'message-date'},`Through ${day}`)),
   el('span',{class:'message-subject'},subject),
   el('span',{class:'message-preview'},plain(issue.result.findings.find(f=>f.kind==='report')?.text||issue.result.issue_summary)),
   el('small',{class:`message-status ${complete?'closed-label':''}`},complete?'No action required':pending?`${pending} ${pending===1?'action':'actions'} to review`:!recommendations.length?'Further review needed':'Decisions saved'));
  nav.append(link);
 }
 sidebar.append(nav);
}
function review(issue,rec,main){
 const saved=savedDecision(issue,rec);main.replaceChildren(el('h2',{class:'review-title'},plain(rec.action)),el('div',{class:'action-reason'},el('h3',{},'Why this is recommended'),p(rec.rationale)));
 const task=section('What needs to be done',
  field('What to deliver',rec.expected_outcome),
  field('Scope',rec.scope),
  field('Question to answer',rec.remaining_question),
  field('People or access needed',rec.expertise_or_access_needed),
  el('h3',{},'How to check the result'),list(rec.evaluation_measures.map(t=>names[t]||natural(t))),
  el('h3',{},'Limits'),list(rec.guardrails),
  field('What approval allows',rec.authorization_boundary));
 const prefix=actionId(issue,rec);
 const owner=el('input',{id:prefix+'-owner','aria-label':'Owner',value:saved?.owner||rec.owner,type:'text',maxlength:200}),priority=el('select',{id:prefix+'-priority','aria-label':'Priority of this work'},['Urgent','High','Moderate','Low'].map(value=>el('option',{value},value)));priority.value=saved?.priority||rec.execution_priority;
 const note=el('textarea',{id:prefix+'-note',maxlength:2000,placeholder:'Add context for the owner, or explain a rejection.'},saved?.note||''),feedback=el('div',{role:'status','aria-live':'polite',class:'decision-feedback'}),receipt=el('div',{class:'receipt'});
 const actions=el('div',{class:'row-start decision-buttons'},...['Proceed','Defer','Reject'].map(choice=>button(choice,()=>decide(choice),choice==='Proceed'?'primary':'')));
 const decision=section('Choose what happens next',p('Assign an owner and priority, then record your decision.','small muted'),el('label',{for:prefix+'-owner'},'Who will own this work?',owner),el('label',{for:prefix+'-priority'},'How soon should this be done?',priority),p(rec.priority_reason,'small muted'),el('label',{for:prefix+'-note'},'Note — required if you reject',note),actions,feedback,receipt);main.append(el('div',{class:'columns review-columns'},task,decision));
 function renderSaved(value){
  feedback.replaceChildren(el('strong',{},({Proceed:'Approved',Defer:'Deferred',Reject:'Rejected'}[value.decision])));
  for(const control of[owner,priority,note,...actions.querySelectorAll('button')])control.disabled=value.decision!=='Defer';
  receipt.replaceChildren();
  if(value.decision==='Proceed'){
   // Upgrade an older approval once, using this same saved recommendation.
   if(!value.ticket){try{value.ticket=prepareTicket(issue,rec,value);localStorage.setItem(decisionKey(issue,rec),JSON.stringify(value));}catch{receipt.append(p('The approval is saved, but its ticket could not be saved. Reload to try again.','small muted'));return;}}
   receipt.append(p('Ticket prepared from this recommendation.','small muted'),el('a',{href:`#view=jira&ticket=${encodeURIComponent(value.ticket.id)}`,class:'back-link'},'View ticket'),button('Download work item',()=>downloadHandoff(issue,rec,value),'quiet'));
  }
 }
 function decide(choice){
  const existing=savedDecision(issue,rec);if(existing&&existing.decision!=='Defer')return;
  if(!owner.value.trim()){feedback.textContent='Enter an owner for this work.';owner.focus();return;}
  if(choice==='Reject'&&!note.value.trim()){feedback.textContent='Add a short reason for rejecting this recommendation.';note.focus();return;}
  const value={decision:choice,owner:owner.value.trim(),priority:priority.value,note:note.value.trim(),recorded_at:new Date().toISOString(),policy_threshold_percent:isCancellation(issue)?null:state.policy.threshold_percent,rubric_sha256:issue.rubric_sha256};
  // One storage write commits the decision and its ticket together.
  try{if(choice==='Proceed')value.ticket=prepareTicket(issue,rec,value);localStorage.setItem(decisionKey(issue,rec),JSON.stringify(value));}catch{feedback.textContent='This browser could not save the decision. Enable local storage and try again.';return;}
  inbox();const inline=document.getElementById(actionId(issue,rec));inline.scrollIntoView({block:'start'});inline.focus({preventScroll:true});
 }
 if(saved)renderSaved(saved);
}
function prepareTicket(issue,rec,decision){return {schema_version:1,id:crypto.randomUUID(),title:rec.action,issue:issue.result.issue_summary,rationale:rec.rationale,scope:rec.scope,store:scopeLine(issue),case_id:issue.case_id,owner:decision.owner,priority:decision.priority,note:decision.note,expected_outcome:rec.expected_outcome,evaluation_measures:rec.evaluation_measures,guardrails:rec.guardrails,authority:rec.authorization_boundary,evidence:issue.result.findings.filter(f=>rec.finding_ids.includes(f.id)),source_run:issue.run_id,recommendation_id:rec.id,decision_recorded_at:decision.recorded_at,review_category:isCancellation(issue)?'cancellation':'delivery',rubric_sha256:issue.rubric_sha256||decision.rubric_sha256||null,policy_threshold_percent:isCancellation(issue)?null:decision.policy_threshold_percent??15,jira_status:'not_sent'};}
function downloadHandoff(issue,rec,decision){const payload=decision.ticket||prepareTicket(issue,rec,decision);const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'})),link=el('a',{href:url,download:`work-item-${rec.id}.json`});document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function openDialog(title){$('dialog-title').textContent=title;if(!$('evidence-dialog').open)$('evidence-dialog').showModal();$('evidence-dialog').scrollTop=0;}
function time(value){if(!value)return 'Not recorded';const date=new Date(value);return isNaN(date)?String(value):date.toLocaleString('en-IN',{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Kolkata'})+' IST';}
function rowList(data){return el('dl',{class:'record-details'},Object.entries(data).filter(([key])=>!['is_synthetic','citation_ref','source_id','text'].includes(key)).map(([key,value])=>[el('dt',{},readable(key)),el('dd',{},value==null?'Not recorded':key.endsWith('_at')?time(value):typeof value==='object'?JSON.stringify(value):values[value]||plain(value))]));}
function recordView(record,multiplicity){return el('article',{class:'source-record'},el('div',{class:'row'},el('strong',{},record.text?'Customer message':'Original record'),el('span',{class:'small muted'},record.order_id?`Order ${record.order_id.split('-ORD-')[1]}`:'No linked order')),record.text?el('blockquote',{},record.text):null,multiplicity>1?p(`${multiplicity} copies were imported; counted once.`,'small muted'):null,el('details',{},el('summary',{},'View the original record'),rowList(record),field('Record reference',record.source_id)));}
async function citation(issue,ref){const epoch=++state.referenceEpoch,[kind,key]=ref.split(':');openDialog(kind==='metric'?readable(key):kind==='source_status'?readable(key):kind==='observation'?'Order timeline':readable(kind));$('dialog-content').replaceChildren(p('Loading the supporting information…','muted'));const{data}=await api(`/api/cases/${issue.case_id}/citation`,{ref});if(epoch!==state.referenceEpoch)return;const target=$('dialog-content');target.replaceChildren();
 if(kind==='metric')target.append(el('div',{class:'metric'},el('strong',{},key==='late_rate'?percent(data.value):number(data.value))),p(natural(data.calculation?.rule||'Calculated from the selected case records.')),p(scopeLine(issue),'small muted'),!isCancellation(issue)?p('Lateness is measured against the delivery promise saved at checkout. A later estimate does not replace it.','small muted'):null);
 else if(kind==='source_status')target.append(p(data.status==='available'?'These records are available.':'These records were unavailable or were not collected for this period.'),p(data.total==null?'The number of records is not known.':`${number(data.total)} records are available.`));
 else if(kind==='observation'){target.append(field('Order',data.order_id),field('Delivery result',data.late?'Delivered after the checkout promise':'Delivered within the checkout promise'),...Object.entries(data.stages).map(([stage,value])=>field(readable(stage),value==null?'Not recorded':`${number(value)} minutes`)));target.append(...Object.entries(data.sources||{}).filter(([,ids])=>ids.length).map(([source])=>button(`Read ${readable(source).toLowerCase()}`,()=>library(issue,source,data.order_id),'quiet')));}
 else target.append(...data.records.map(r=>recordView(r)));target.append(button('Browse the supporting records',()=>library(issue),'quiet'));
}
async function library(issue=state.issue||state.issues[0],source='feedback',order=''){
  if(!issue)return;openDialog('Records for this case');++state.referenceEpoch;
 const sourceSelect=el('select',{'aria-label':'Type of evidence'},Object.keys(issue.coverage).map(s=>el('option',{value:s},readable(s))));sourceSelect.value=source;
 const input=el('input',{type:'text',value:order,placeholder:'Enter the complete order reference','aria-label':'Order reference'}),results=el('div',{'aria-live':'polite'});let offset=0;
 async function load(){const epoch=++state.referenceEpoch;results.replaceChildren(p('Loading records…','muted'));let data;try{data=await api(`/api/cases/${issue.case_id}/evidence`,{source:sourceSelect.value,offset,...(input.value.trim()?{order_id:input.value.trim()}:{})});}catch{if(epoch===state.referenceEpoch)results.replaceChildren(el('div',{class:'notice error',role:'alert'},p('That order reference could not be used. Enter a reference from this issue or clear the filter.')));return;}if(epoch!==state.referenceEpoch)return;results.replaceChildren();if(data.status!=='available'){results.append(p('These records were not available for the period being reviewed. The investigation has not assumed they contain no events.','notice neutral'));return;}if(!data.records.length){results.append(p('No records match this order reference. Clear the filter to browse all records.','empty'));return;}results.append(p(`Showing records ${offset+1}–${offset+data.records.length} of ${number(data.total)}.`,'small muted'),...data.records.map(r=>recordView(r,data.source_multiplicities[r.source_id])));const prev=button('Previous records',()=>{offset=Math.max(0,offset-10);return load();});prev.disabled=offset===0;const next=button('Next records',()=>{offset=data.next_offset;return load();});next.disabled=data.next_offset==null;results.append(el('div',{class:'row pagination'},prev,next));}
 sourceSelect.addEventListener('change',()=>{offset=0;safe(load);});input.addEventListener('keydown',event=>{if(event.key==='Enter'){offset=0;safe(load);}});
 $('dialog-content').replaceChildren(p(scopeLine(issue),'small muted'),el('label',{},'What would you like to inspect?',sourceSelect),el('div',{class:'order-filter'},el('label',{},'Filter by order reference — optional',input),button('Find order',()=>{offset=0;return load();}),button('Clear filter',()=>{offset=0;input.value='';return load();},'quiet')),results);await load();
}
$('close-rubric').addEventListener('click',()=>$('rubric-dialog').close());$('reset-demo').addEventListener('click',()=>safe(resetDemo));$('library').addEventListener('click',()=>safe(()=>library()));$('close-dialog').addEventListener('click',()=>{$('evidence-dialog').close();++state.referenceEpoch;});$('evidence-dialog').addEventListener('cancel',()=>++state.referenceEpoch);window.addEventListener('hashchange',()=>safe(route));window.addEventListener('popstate',()=>safe(route));initFeedback();safe(route);
