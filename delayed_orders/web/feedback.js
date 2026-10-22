'use strict';
const FEEDBACK_VISITOR_KEY='insightbridge-feedback-visitor-v1',FEEDBACK_SESSION_KEY='insightbridge-feedback-session-v1',FEEDBACK_DRAFT_KEY='insightbridge-feedback-draft-v1';
const feedbackState={identity:null,draft:null,pending:null};
function feedbackId(){return crypto.randomUUID().replaceAll('-','');}
function initFeedback(){
 let visitor,session,draft;
 try{visitor=localStorage.getItem(FEEDBACK_VISITOR_KEY);}catch{}
 if(!/^[a-f0-9]{32}$/.test(visitor||'')){visitor=feedbackId();try{localStorage.setItem(FEEDBACK_VISITOR_KEY,visitor);}catch{}}
 try{session=JSON.parse(sessionStorage.getItem(FEEDBACK_SESSION_KEY));draft=JSON.parse(sessionStorage.getItem(FEEDBACK_DRAFT_KEY));}catch{}
 if(!/^[a-f0-9]{32}$/.test(session?.session_id||'')||!/^[a-f0-9]{32}$/.test(session?.visit_id||''))session={session_id:feedbackId(),visit_id:feedbackId()};
 try{sessionStorage.setItem(FEEDBACK_SESSION_KEY,JSON.stringify(session));}catch{}
 feedbackState.identity={visitor_id:visitor,session_id:session.session_id};
 feedbackState.draft={rating:Number.isInteger(draft?.rating)&&draft.rating>=1&&draft.rating<=5?draft.rating:0,comment:typeof draft?.comment==='string'?draft.comment.slice(0,3000):''};
 feedbackState.pending=draft?.pending||null;
 feedbackPost('/api/feedback/events',{...feedbackState.identity,event_id:session.visit_id,event:'visit',source:'page'}).catch(()=>{});
 $('open-feedback').addEventListener('click',event=>{event.preventDefault();openFeedback();});
 $('close-feedback').addEventListener('click',()=>$('feedback-dialog').close());
 document.addEventListener('click',event=>{
  const target=event.target.closest('a,button');if(!target)return;
  const label=target.textContent.trim();
  const sources={'GPT-5.4':'run_54','GPT-6 Astra':'run_astra','Leave feedback':'header','Customer issues':'customer_issues','View AI framework':'framework','View saved traces':'run_trace','View tickets':'jira'};
  const source=sources[label];
  if(source)feedbackPost('/api/feedback/events',{...feedbackState.identity,event_id:feedbackId(),event:'click',source}).catch(()=>{});
 });
}
function feedbackPost(path,data){return api(path,null,{method:'POST',headers:{'Content-Type':'application/json','X-ProductOps-Request':'feedback'},body:JSON.stringify(data),keepalive:true});}
function persistFeedbackDraft(){try{sessionStorage.setItem(FEEDBACK_DRAFT_KEY,JSON.stringify({...feedbackState.draft,pending:feedbackState.pending}));}catch{}}
function openFeedback(){
 $('feedback-dialog-content').replaceChildren(feedbackForm(()=>{
  $('feedback-dialog-content').replaceChildren(el('p',{class:'feedback-thanks',role:'status'},'Thank you! Your feedback has been saved.'),button('Close',()=>$('feedback-dialog').close(),'primary'));
 }));
 $('feedback-dialog').showModal();
}
function feedbackForm(onSaved){
 const draft=feedbackState.draft||{rating:0,comment:''};
 const suffix=feedbackId(),status=el('p',{class:'feedback-status',role:'status','aria-live':'polite'});
 const form=el('form',{class:'feedback-form','aria-label':'Share feedback'});
 const comment=el('textarea',{id:'feedback-comment-'+suffix,rows:3,maxlength:3000,placeholder:'What worked well? What could be better?'},draft.comment);
 const ratingText=el('span',{class:'small muted'},draft.rating?`${draft.rating} of 5 stars`:'Choose a rating');
 const stars=el('div',{class:'feedback-stars'});
 let rating=draft.rating;
 for(let value=1;value<=5;value++){
  const input=el('input',{type:'radio',name:'rating-'+suffix,value,required:'','aria-label':`${value} ${value===1?'star':'stars'}`});input.checked=rating===value;
  const label=el('label',{'data-active':String(value<=rating)},input,el('span',{'aria-hidden':'true'},'★'));
  input.addEventListener('change',()=>{rating=value;ratingText.textContent=`${value} of 5 stars`;for(const [i,node] of [...stars.children].entries())node.dataset.active=String(i<rating);saveDraft();});
  stars.append(label);
 }
 function saveDraft(){feedbackState.draft={rating,comment:comment.value};persistFeedbackDraft();}
 comment.addEventListener('input',saveDraft);
 const submit=el('button',{type:'submit',class:'primary'},'Send feedback');
 form.append(el('fieldset',{class:'feedback-rating'},el('legend',{},'Star rating (required)'),stars,ratingText),
  el('label',{for:comment.id},'Your feedback (optional)',comment),
  submit,status);
 form.addEventListener('submit',async event=>{
  event.preventDefault();if(submit.disabled||!form.reportValidity())return;
  saveDraft();
  const data={...feedbackState.identity,...feedbackState.draft,name:'Anonymous',company:'',source:'header',context:{}};
  const fingerprint=JSON.stringify(data);
  if(feedbackState.pending?.fingerprint!==fingerprint)feedbackState.pending={fingerprint,event_id:feedbackId()};
  persistFeedbackDraft();submit.disabled=true;status.textContent='Saving your feedback…';
  try{
   await feedbackPost('/api/feedback',{...data,event_id:feedbackState.pending.event_id});
   feedbackState.pending=null;feedbackState.draft={rating:0,comment:''};persistFeedbackDraft();
   if(onSaved)onSaved();else form.replaceChildren(el('p',{class:'feedback-thanks',role:'status'},'Thank you! Your feedback has been saved.'));
  }catch(error){status.textContent=`Could not save feedback. ${error.message}`;submit.disabled=false;}
 });
 return form;
}
