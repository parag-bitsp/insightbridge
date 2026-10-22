'use strict';
function combineSavedTraces(traces){
 const first=traces[0];
 const totals=Object.fromEntries(Object.keys(first.totals).map(key=>[key,key==='estimated_cost_usd'?(traces.some(t=>t.totals[key]!=null)?traces.reduce((sum,t)=>sum+(t.totals[key]||0),0):null):traces.reduce((sum,t)=>sum+(t.totals[key]||0),0)]));
 const stamps=key=>traces.map(t=>t[key]).filter(Boolean).sort();
 return {...first,run_id:traces.map(t=>t.run_id).join(', '),kind:traces.length===1?first.kind:'Saved model analysis',
  status:traces.every(t=>t.status===first.status)?first.status:'mixed',published:traces.every(t=>t.published),
  started_at:stamps('started_at')[0],finished_at:stamps('finished_at').at(-1),
  completed_cases:traces.reduce((sum,t)=>sum+(t.completed_cases||0),0),total_cases:traces.reduce((sum,t)=>sum+(t.total_cases||0),0),
  error:traces.map(t=>t.error).filter(Boolean).join(' ')||null,
  interpretation:traces.flatMap(t=>t.interpretation),interpretation_recorded:traces.every(t=>t.interpretation_recorded),
  interpretation_reserved_micro_usd:traces.reduce((sum,t)=>sum+(t.interpretation_reserved_micro_usd||0),0),
  cases:traces.flatMap(t=>t.cases.map(item=>({...item,source_run:t.run_id}))),totals};
}
async function traceHome(epoch,runId){
 const content=el('div',{'aria-live':'polite'},p('Loading saved runs...','loading'));
 $('main').replaceChildren(el('section',{class:'reference-page trace-page'},
  el('a',{href:'#home',class:'back-link'},'Back to home'),el('h1',{},'Run trace & cost'),
  p('Compare the saved GPT-6 Astra and GPT-5.4 runs.'),content));
 const saved=await Promise.all(['astra','latency'].map(mode=>cachedDemo(mode)));
 if(epoch!==state.epoch)return;
 const selectedId=saved.find(d=>d.cache_mode===runId||d.trace_runs.includes(runId))?.cache_mode||(['astra','latency'].includes(state.analysisMode)?state.analysisMode:'astra');
 const frozen=saved.find(d=>d.cache_mode===selectedId);
 const batches=await Promise.all(frozen.trace_runs.map(id=>api(`/api/traces/${encodeURIComponent(id)}`)));
 if(epoch!==state.epoch)return;
 const trace=combineSavedTraces(batches);
 const pinnedCases=frozen.sources.map(source=>source.case_id);
 const picker=el('select',{'aria-label':'Saved run'},saved.map(d=>el('option',{value:d.cache_mode},d.cache_mode==='latency'?'GPT-5.4':'GPT-6 Astra')));
 picker.value=selectedId;
 picker.addEventListener('change',()=>{location.hash=`view=trace&run=${picker.value}`;});
 const details=(label,...children)=>el('details',{},el('summary',{},label),...children);
 const json=value=>el('pre',{class:'trace-json'},JSON.stringify(value,null,2));
 const heading=item=>`${item.case_id} (${item.source_run.slice(-8)}) · ${item.category}`;
 const duration=value=>typeof value==='number'?`${value.toFixed(2)} s`:'Not recorded';
 const tokenText=totals=>`${number(totals.total_tokens)} tokens${totals.missing_usage_calls?' recorded (partial)':''}: ${number(totals.input_tokens)} input, including ${number(totals.cached_input_tokens)} cached; ${number(totals.output_tokens)} output.`;
 const callNodes=(calls,prefix)=>calls.map((call,index)=>details(`${prefix} · call ${index+1} · ${call.phase.replaceAll('_',' ')} · ${call.status}`,
  p(`${call.model||'Model not recorded'} · ${duration(call.duration_seconds)}`,'small muted'),
  p(call.total_tokens==null?'Token usage not recorded.':`${number(call.input_tokens)} input (${call.cached_input_tokens==null?'cache usage not recorded':`${number(call.cached_input_tokens)} cached`}), ${number(call.output_tokens)} output.`, 'small'),
  call.validation_error?p(call.validation_error,'notice neutral'):null,
  details('Request supplied to the model',json(call.request)),details('Response from the model',json(call.response))));
 const row=(label,summary,...children)=>el('tr',{},el('th',{scope:'row'},label),el('td',{},summary,...children));
 const readingLabel=trace.interpretation.some(call=>call.phase==='framework_reading')?'Framework reading':'Rubric interpretation';
 const allCalls=[...trace.interpretation,...trace.cases.flatMap(item=>item.calls)];
 const correctionCount=allCalls.filter(call=>call.phase==='validation_correction').length;
 const table=el('table',{class:'trace-table'},el('caption',{class:'small muted'},'Saved run overview'),
  el('thead',{},el('tr',{},el('th',{scope:'col'},'Detail'),el('th',{scope:'col'},'What happened'))),el('tbody',{},
   row('Investigation flow',p(trace.kind==='Rubric interpretation'?'Rubric interpretation failed before case investigations started.':`${readingLabel} → case investigations → validation → results. Status: ${trace.status}.`),
    trace.status==='running'?p(`${trace.completed_cases||0} of ${trace.total_cases||trace.cases.length} cases completed. Refresh to see saved progress; call records appear when each case finishes.`,'small muted'):null,
    details('View stages and validation',p(trace.published?'All case results passed validation and were published.':trace.kind==='Archived investigation'?'Archived investigation; publication under the current rubric is not established.':'Results from this run have not been published.'),
     p('Validation checks structure, figures and citations. Explanation quality still requires human review.','small muted'),
     trace.error?p(trace.error,'notice error'):null,
     list(trace.cases.map(item=>`${heading(item)}: ${item.status}; validation ${item.validation}.`)),
     p(`Started: ${time(trace.started_at)}. Finished: ${time(trace.finished_at)}.`,'small muted'))),
   row('Context isolation',p('Inspect each case’s evidence and the exact rubric context supplied.'),
    details('View case context',...trace.cases.map(item=>el('section',{},el('h3',{},heading(item)),
     item.evidence_files.length?list(item.evidence_files):p('Evidence file provenance not recorded.','muted'),
     p(item.rubric_sha256?`Rubric SHA-256: ${item.rubric_sha256}`:'Rubric provenance not recorded for this case.','small muted'),
     details('View supplied context',...item.calls.map((call,index)=>details(`Call ${index+1} context`,json(call.request.input||[])))))))),
   row('Model calls',p(`${trace.totals.calls} recorded calls; ${correctionCount} validation correction${correctionCount===1?'':'s'}. No automatic transport retries.`),
    details('View calls, requests and responses',...callNodes(trace.interpretation,readingLabel),
     ...trace.cases.flatMap(item=>callNodes(item.calls,item.case_id)),
     !trace.interpretation_recorded?p('Rubric interpretation trace not recorded for this older run.','small muted'):null,
     p('Call duration measures the generation request. Case duration also includes preparation, token counting and validation.','small muted'))),
   row('Token usage',p(tokenText(trace.totals)),
    details('View usage by case',...trace.cases.map(item=>p(`${heading(item)}: ${item.totals.calls?tokenText(item.totals):'No recorded calls.'}`)),
     trace.totals.missing_usage_calls?p(`${trace.totals.missing_usage_calls} call(s) have missing usage; totals include recorded usage only.`,'notice neutral'):null,
     p('Cached input is part of input tokens and is counted once in the total.','small muted'))),
   row('Estimated cost',el('div',{id:'trace-cost-summary'}),el('div',{id:'trace-cost-details'}))));
 const rates={};const rateControls=el('div',{class:'trace-rates'});
 for(const [key,label] of [['input_per_million','Input'],['cached_input_per_million','Cached input'],['output_per_million','Output']]){
  const input=el('input',{type:'number',min:'0',max:'10000',step:'any',value:trace.pricing[key],'aria-label':`${label} USD per million tokens`});
  rates[key]=input;rateControls.append(el('label',{},`${label} / 1M tokens (USD)`,input));
  input.addEventListener('input',recalculate);
 }
 function cost(calls,prices){
  let total=0,known=0;
  for(const call of calls){const callRates=call.model===trace.pricing.model?prices:call.pricing;if(call.total_tokens==null||!callRates)continue;known++;
   const cached=call.cached_input_tokens||0;
   const writes=call.cache_write_tokens||0;
   total+=((call.input_tokens-cached-writes)*callRates.input_per_million+writes*(call.pricing?.cache_write_per_million||callRates.input_per_million)+cached*callRates.cached_input_per_million+call.output_tokens*callRates.output_per_million)/1e6;
  }
  return {total,known};
 }
 function recalculate(){
  const prices=Object.fromEntries(Object.entries(rates).map(([key,input])=>[key,input.value.trim()===''?NaN:Number(input.value)]));
  if(Object.values(prices).some(value=>!Number.isFinite(value)||value<0||value>10000)){
   $('trace-cost-summary').replaceChildren(p('Enter rates from 0 to 10,000 USD per million tokens.','notice error'));$('trace-cost-details').replaceChildren();return;
  }
  const estimate=cost(allCalls,prices),money=value=>`$${value.toFixed(6)}`;
  const partial=estimate.known<allCalls.length||['running','interrupted'].includes(trace.status)||!trace.interpretation_recorded&&trace.kind==='Rubric review';
  $('trace-cost-summary').replaceChildren(p(estimate.known?`${money(estimate.total)} USD${partial?' for recorded usage (partial estimate)':''}.`:'Cost unavailable: no priced usage recorded.'),
   p('Estimated token cost, not a billing statement. Budget reservations are shown separately.','small muted'));
  const costLine=(label,calls)=>{const item=cost(calls,prices);return p(`${label}: ${item.known?money(item.total)+' USD'+(item.known<calls.length?' (partial)':''):'Not available'}`);};
  $('trace-cost-details').replaceChildren(details('View cost by call and case',costLine(readingLabel,trace.interpretation),
   trace.interpretation_reserved_micro_usd?p(`Unsettled rubric budget reservation: ${money(trace.interpretation_reserved_micro_usd/1e6)} USD. This is not confirmed spend.`,'notice neutral'):null,
   ...trace.cases.map(item=>el('section',{},el('h3',{},heading(item)),costLine('Case estimate',item.calls),
    ...item.calls.map((call,index)=>costLine(`Call ${index+1}`,[call])),
    item.reserved_micro_usd?p(`Unsettled budget reservation: ${money(item.reserved_micro_usd/1e6)} USD. This is not confirmed spend.`,'notice neutral'):null)),
   trace.totals.unknown_cache_calls?p('Some calls lack cache details; their input is estimated at the full input rate.','small muted'):null));
 }
 content.replaceChildren(el('div',{class:'row trace-toolbar'},el('label',{},'Saved run',picker)),
  p(`Run ${trace.run_id}`,'small muted'),p(`${trace.analysis_mode==='astra'?'Astra comparison':trace.analysis_mode==='latency'?'Optimize for latency':'Optimize for cost'} · ${trace.analysis_model||trace.pricing.model}`,'small muted'),
  pinnedCases.length?p(`The frozen demo uses the validated ${pinnedCases.join(', ')} results from this batch. Original batch status and any other failed case attempts remain recorded below.`,'small muted'):null,table,
  details('Adjust cost calculator rates',p(`${trace.pricing.model} · USD per million tokens. Changes recalculate this page only; budget enforcement is unchanged.`,'small muted'),rateControls,
   el('a',{href:trace.pricing.source,target:'_blank',rel:'noopener noreferrer'},`OpenAI pricing · verified ${trace.pricing.verified_on}`)),
  p('Opening or refreshing a trace reads saved records and makes no LLM calls.','small muted'));
 recalculate();
}
