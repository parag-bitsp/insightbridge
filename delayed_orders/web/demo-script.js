'use strict';
function demoScriptDocument(text){
 const article=el('article',{class:'rubric-document demo-script-document'});
 const inline=(node,text)=>{
  for(const part of text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)){
   if(part.startsWith('**'))node.append(el('strong',{},part.slice(2,-2)));
   else if(part.startsWith('`'))node.append(el('code',{},part.slice(1,-1)));
   else node.append(document.createTextNode(part));
  }
  return node;
 };
 let paragraph=[],list=null,table=null;
 function flush(){if(paragraph.length){article.append(inline(el('p',{}),paragraph.join(' ')));paragraph=[];}}
 for(const raw of text.split(/\r?\n/)){
  const line=raw.trim();
  if(!line){flush();list=null;table=null;continue;}
  const heading=line.match(/^(#{1,3})\s+(.*)$/);
  if(heading){flush();list=null;table=null;if(heading[1].length>1)article.append(inline(el(heading[1].length===2?'h3':'h4',{}),heading[2]));continue;}
  if(line.startsWith('|')){
   flush();list=null;if(/^\|[\s:|\-]+\|$/.test(line))continue;
   const cells=line.slice(1,-1).split('|').map(cell=>cell.trim());
   if(!table){table=el('table',{class:'demo-script-qa'},el('thead',{},el('tr',{},...cells.map(cell=>inline(el('th',{scope:'col'}),cell)))),el('tbody',{}));article.append(table);}
   else table.querySelector('tbody').append(el('tr',{},...cells.map(cell=>inline(el('td',{}),cell))));
   continue;
  }
  if(line.startsWith('- ')){flush();table=null;if(!list){list=el('ul',{});article.append(list);}list.append(inline(el('li',{}),line.slice(2)));continue;}
  if(line.startsWith('**')){flush();article.append(inline(el('p',{class:'demo-script-cue'}),line));continue;}
  if(line.startsWith('“')){flush();article.append(inline(el('blockquote',{}),line));continue;}
  paragraph.push(line);
 }
 flush();return article;
}
async function openFullDemoScript(){
 const dialog=$('demo-script-dialog'),content=$('demo-script-content');
 content.replaceChildren(p('Loading the demo script...'));
 if(!dialog.open)dialog.showModal();
 try{const result=await api('/api/demo-script');content.replaceChildren(demoScriptDocument(result.text));content.scrollTop=0;}
 catch(error){content.replaceChildren(p(`Could not load the demo script. ${error.message}`));}
}
const DEMO_PROGRESS_KEY='insightbridge-demo-script-astra-v1';
const DEMO_STEPS=[
 {title:'Start with the decision framework',href:'#home',action:'Open AI framework',framework:true,
  instruction:'Read the decision rules, model behaviour guidelines, roles and evaluation rubric. Close the document to continue.',
  expect:'Rules define when work is needed and who owns it. The leading Astra result is an earlier saved run; opening the current framework does not rerun it.'},
 {title:'Read the customer issues',href:'#view=evidence',
  instruction:'Browse the customer messages. Notice the store, product and reported problem. These reports are the starting point for the review.',
  expect:'Customer messages describe individual experiences. Operating records establish the wider pattern.'},
 {title:'Review the delivery delay',href:'#issue=GG-01',
  instruction:'Read Store A’s issue description and findings. Open supporting records if useful, then close them.',
  expect:'24 of 120 orders were late: 20%, above the 15% threshold. Long rider waits after packing need a focused dispatch review.'},
 {title:'Review the engineering recommendation',href:'#issue=CC-01&view=actions',action:'Open engineering recommendation',
  instruction:'Read the milk checkout proposal under Remedial actions. Show What needs to be done and the availability and checkout engineering owner. Review the design, test plan and rollback plan.',
  expect:'Checkout should stop accepting milk when recorded stock reaches zero, without waiting for the scheduled refresh. Engineering must test restocking, delayed or repeated updates, and checkout speed. Implementation and rollout need separate approval.'},
 {title:'Check when no action is needed',href:'#issue=GG-03',
  instruction:'Read Store C’s delivery issue. Review why no remedial action is proposed.',
  expect:'This case is below the action threshold. A complaint does not automatically justify another task.'},
 {title:'Record a human decision',href:'#issue=CC-01&view=actions',
  instruction:'Return to the engineering proposal for milk checkout. Review the owner and priority, then select Proceed. If an approval already exists, inspect it and continue.',
  expect:'Proceed approves the stated proposal work and prepares a ticket draft. It does not implement or deploy the change.'},
 {title:'Open the ticket draft',href:'#view=jira',
  instruction:'Select the milk ticket in the list. Read its scope and acceptance criteria in the scrollable dialog, then close it.',
  expect:'Multiple tickets stay in a list. Decisions are saved in this browser. No ticket is sent to Jira.'},
 {title:'Inspect the audit and compare',href:'#view=trace&run=astra',
  instruction:'Review Astra’s saved calls, tokens and cost. Then select GPT-5.4 to compare its saved output and framework-reading call.',
  expect:'Astra has four recommendations; GPT-5.4 has eight. Compare usefulness, not just count. These runs used different framework versions and are not a controlled benchmark.'}
];
function initDemoScript(){
 let step=0,open=false;
 try{const saved=JSON.parse(sessionStorage.getItem(DEMO_PROGRESS_KEY));if(Number.isInteger(saved?.step)&&saved.step>=0&&saved.step<DEMO_STEPS.length){step=saved.step;open=saved.open===true;}}catch{}
 const dock=el('aside',{class:'demo-script-dock','aria-label':'Demo walkthrough tools'});
 const panel=el('section',{id:'demo-script-panel',class:'demo-script-panel',role:'region','aria-label':'Demo script'});
 const toggle=button('Demo script',()=>show(!open),'demo-script-toggle');
 toggle.setAttribute('aria-controls','demo-script-panel');
 function remember(){try{sessionStorage.setItem(DEMO_PROGRESS_KEY,JSON.stringify({step,open}));}catch{}}
 function show(value,focus=true){open=value;remember();render();if(focus)(open?panel.querySelector('button'):toggle).focus();}
 async function navigate(){
  const data=await cachedDemo('astra');useFrozenDemo(data);state.issue=null;state.actions={};state.tabs={};
  try{localStorage.setItem(ANALYSIS_MODE_KEY,'astra');}catch{}
  if($('ticket-dialog').open)$('ticket-dialog').close();
  if(location.hash!==DEMO_STEPS[step].href)history.pushState(null,'',DEMO_STEPS[step].href);
  await route();
  if(DEMO_STEPS[step].framework){const link=[...document.querySelectorAll('a')].find(a=>a.textContent==='View AI framework');if(link)link.click();}
 }
 function change(value){step=value;remember();render();panel.querySelector('h2').focus();}
 function render(){
  toggle.setAttribute('aria-expanded',String(open));panel.hidden=!open;
  document.body.classList.toggle('demo-guide-open',open);
  if(!open)return;
  const current=DEMO_STEPS[step],previous=button('Previous step',()=>change(step-1),'quiet');previous.disabled=step===0;
  panel.replaceChildren(
   el('div',{class:'demo-script-heading'},el('span',{},`Step ${step+1} of ${DEMO_STEPS.length}`),el('button',{type:'button','aria-label':'Close demo script',onClick:()=>show(false)},'×')),
   el('div',{class:'demo-script-body','aria-live':'polite'},el('h2',{tabindex:'-1'},current.title),p(current.instruction),
    el('div',{class:'demo-expected'},el('strong',{},'What to look for'),p(current.expect)),
    el('a',{href:current.href,class:'demo-step-link',onClick:event=>{event.preventDefault();safe(navigate);}},current.action||'Open this screen')),
   el('div',{class:'demo-script-controls'},previous,step<DEMO_STEPS.length-1?button('Next step',()=>change(step+1),'primary'):button('Finish walkthrough',()=>show(false),'primary')),
   el('a',{href:'#demo-script',class:'demo-script-full',onClick:event=>{event.preventDefault();openFullDemoScript();}},'Read full guide'));
 }
 panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.stopPropagation();show(false);}});
 dock.append(panel,toggle);document.body.append(dock);render();
 $('close-demo-script').addEventListener('click',()=>$('demo-script-dialog').close());
 if(location.hash==='#demo-script')show(true,false);
}
document.addEventListener('DOMContentLoaded',initDemoScript);
