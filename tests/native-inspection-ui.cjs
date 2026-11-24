// DOM-contract fixture, not a browser/rendering or target-device acceptance test.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const inspection=require('../fidelis/studio/inspection.js');
const review=require('../fidelis/studio/review-ui.js');
const html=fs.readFileSync(process.argv[2],'utf8');
const elements=new Map();
class Element{
 constructor(){this.children=[];this.style={};this.dataset={};this.handlers={};this.value='';this.hidden=false;this.disabled=false;this.options=[];const on=new Set();this.classList={toggle(name,force){const next=force===undefined?!on.has(name):!!force;if(next)on.add(name);else on.delete(name);return next;},add(name){on.add(name);},remove(name){on.delete(name);},contains(name){return on.has(name);}};this.attributes={};this.tagName='DIV';}
 set id(value){this._id=value;elements.set(value,this);}
 get id(){return this._id;}
 addEventListener(type,handler){this.handlers[type]=handler;}
 removeAttribute(key){delete this.attributes[key];}
 setAttribute(key,value){this.attributes[key]=value;}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=children;}
 scrollIntoView(){}
 dispatchEvent(event){const type=event&&event.type;if(typeof this['on'+type]==='function')this['on'+type](event);if(typeof this.handlers[type]==='function')this.handlers[type](event);}
 getBoundingClientRect(){return {left:0,top:0,width:800,height:600};}
 getContext(){return {clearRect(){},putImageData(){},createImageData(){return {data:new Uint8ClampedArray(0)}}};}
}
for(const match of html.matchAll(/id="([^"]+)"/g))elements.set(match[1],new Element());
for(const [id,value] of Object.entries({nativeZoom:'1',nativeRole:'master',nativeSide:'256',nativeSplit:'50',paintMode:'off',brushSize:'48',overlayOpacity:'0.6',paintLayer:'protected'}))elements.get(id).value=value;
elements.get('nativePanel').hidden=true;
const pending=[];
class FixtureImage extends Element{
 set src(value){this.url=value;pending.push(this);}
}
class History{constructor(){this.done=[];this.undone=[];this.dirty=false;}reset(){this.done=[];this.undone=[];this.dirty=false;}strokes(){return []}}
const timers=[];
const context={console,URLSearchParams,Image:FixtureImage,FidelisInspection:inspection,FidelisReview:review,FidelisMaskHistory:History,Event,
 document:{getElementById:id=>elements.get(id),createElement:()=>new Element(),activeElement:{tagName:'DIV'}},
 window:{listeners:{},innerWidth:1440,addEventListener(type,handler){(this.listeners[type]||=[]).push(handler);}},
 timers,setTimeout(fn,delay){timers.push({fn,delay});return timers.length;},clearTimeout(id){if(!id||!timers[id-1])return;timers[id-1].fn=null;},requestAnimationFrame(){},confirm:()=>true,
 fetch:async()=>({ok:true,json:async()=>({jobs:[],profiles:{},generation_enabled:false})}),Option:function(){}};
vm.createContext(context);
const code=html.match(/<script>([\s\S]*?)<\/script>/)[1];vm.runInContext(code,context);
function run(code){return vm.runInContext(code,context);}
async function flush(){for(let i=0;i<8;i++)await Promise.resolve();}
function finish(images){for(const image of images){const params=new URL(image.url,'http://localhost').searchParams;image.naturalWidth=Number(params.get('width'));image.naturalHeight=Number(params.get('height'));image.onload();}}
(async()=>{
 await flush();
 run(`setJob({id:'job-a',revision:3,dimensions:[8001,6003],label:'Fixture',profile:'luxury_apparel',blend:{skin:0,hair:0,fabric:0,edge_protection:0}});history.done.push({unsaved:true});history.dirty=true;dirtyBlend=true;`);
 elements.get('inspectNative').onclick();assert.equal(pending.length,2);assert.equal(elements.get('nativePanel').hidden,false);
 assert.equal(elements.get('nativePair').children.length,0);
 finish([pending[0]]);await flush();assert.equal(elements.get('nativePair').children.length,0);
 finish([pending[1]]);await flush();
 const images=elements.get('nativePair').children;
 assert.equal(images.length,2);assert.match(images[1].alt,/base/);assert.match(images[0].alt,/final/);
 assert.equal(images[1].style.clipPath,'inset(0 50% 0 0)');
 assert.equal(elements.get('nativePair').style.width,'256px');
 assert.equal(run('history.done.length'),1);assert.equal(run('dirtyBlend'),true);
 assert.equal(elements.get('checkNativeStructure').disabled,false);
 assert.equal(elements.get('lockNativeStructure').disabled,true);
 await elements.get('lockNativeStructure').onclick();
 assert.match(elements.get('error').textContent,/Save or discard unsaved edits/);

 elements.get('nativeZoom').value='2';elements.get('nativeZoom').onchange();
 assert.equal(elements.get('nativePair').style.width,'512px');assert.equal(images[0].style.width,'512px');assert.equal(images[1].style.width,'512px');
 elements.get('nativeSplit').value='25';elements.get('nativeSplit').oninput();assert.equal(images[1].style.clipPath,'inset(0 75% 0 0)');
 assert.match(elements.get('nativeStatus').textContent,/Saved revision 3/);
 // An old selection cannot reappear after switching jobs.
 elements.get('nativeLoad').onclick();const old=pending.slice(2);
 run(`setJob({id:'job-b',revision:1,dimensions:[12,8],label:'B',profile:'luxury_apparel',blend:{skin:0,hair:0,fabric:0,edge_protection:0}})`);
 finish(old);await flush();assert.equal(elements.get('nativePanel').hidden,true);assert.equal(elements.get('nativePair').children.length,0);
 // A partial failed pair stays hidden, rather than showing an old base/result.
 elements.get('inspectNative').onclick();const bad=pending.slice(4);finish([bad[0]]);bad[1].onerror();await flush();
 assert.equal(elements.get('nativeScroll').hidden,true);assert.equal(elements.get('nativePair').children.length,0);assert.match(elements.get('nativeStatus').textContent,/reload the job/);
 // Suggestion controls require explicit review and retain unsaved work.
 run(`history.done.push({unsaved:true});history.dirty=true;dirtyBlend=true;busy=false;`);
 await elements.get('stageSuggestion').onclick();
 assert.match(elements.get('error').textContent,/Save or discard unsaved edits/);
 assert.equal(run('history.done.length'),1);assert.equal(run('dirtyBlend'),true);
 run(`setJob({id:'job-c',revision:2,dimensions:[12,8],label:'C',profile:'luxury_apparel',blend:{skin:0,hair:0,fabric:0,edge_protection:0},mask_suggestion:{status:'staged',staged_revision:2,score_acceptance_fraction:.25}});controls();`);
 assert.equal(elements.get('acceptSuggestion').disabled,false);
 elements.get('showSuggestion').checked=true;elements.get('showSuggestion').onchange();
 assert.equal(elements.get('suggestionOverlay').hidden,false);assert.match(elements.get('suggestionOverlay').src,/suggestion-preview\?revision=2/);
 run('current.revision=3;controls()');assert.equal(elements.get('acceptSuggestion').disabled,true);assert.equal(elements.get('discardSuggestion').disabled,false);
 elements.get('paintMode').value='paint';elements.get('paintMode').handlers.change();
 assert.equal(elements.get('suggestionOverlay').hidden,true);
 // A successful lock uses the displayed crop and reloads it on the new revision.
 run("current.mask_suggestion=null; $('nativeRole').value='texture';");
 elements.get('inspectNative').onclick();
 finish(pending.slice(-2));await flush();
 const structureRequests=[];
 context.fetch=async(path,options)=>{
  structureRequests.push([path, options.body && JSON.parse(options.body)]);
  const payload=path.endsWith('/inspect-structure')?{regions:[{changed_pixels:4,pixels:96,strong_edge_disagreements:1}]}:
   path.endsWith('/lock-structure')?{...run('current'),revision:4}:{jobs:[],profiles:{},generation_enabled:false};
  return {ok:true,json:async()=>payload};
 };
 await elements.get('checkNativeStructure').onclick();
 assert.match(elements.get('nativeStructureStatus').textContent,/4 of 96 pixels/);
 await elements.get('lockNativeStructure').onclick();
 assert.deepEqual(structureRequests[0],[ '/api/regions/jobs/job-c/inspect-structure',
  {expected_revision:3,regions:[[0,0,12,8]],target:'texture'}]);
 assert.deepEqual(structureRequests[1],[ '/api/regions/jobs/job-c/lock-structure',
  {expected_revision:3,regions:[[0,0,12,8]]}]);
 assert.equal(elements.get('nativePanel').hidden,false);
 assert.equal(elements.get('nativeRole').value,'master');
 assert.match(pending.at(-1).url,/revision=4/);
 assert.match(elements.get('jobChip').textContent,/revision 4/);
 assert.doesNotMatch(elements.get('jobChip').textContent,/unsaved/);
 elements.get('paintMode').value='off';
 const x0=Number(elements.get('nativeX').value);
 const beforeNudge=pending.length;
 context.window.listeners.keydown[0]({key:'ArrowRight',ctrlKey:false,metaKey:false,altKey:false,shiftKey:false,preventDefault(){}});
 assert.equal(Number(elements.get('nativeX').value),x0+1);
 assert.equal(pending.length,beforeNudge);
 assert.equal(context.timers.some(timer=>timer.delay===120&&timer.fn),true);
 context.document.activeElement={tagName:'INPUT',type:'number'};
 context.window.listeners.keydown[0]({key:'ArrowRight',ctrlKey:false,metaKey:false,altKey:false,shiftKey:false,preventDefault(){}});
 assert.equal(Number(elements.get('nativeX').value),x0+1);
 context.document.activeElement={tagName:'DIV'};
 elements.get('channelSkin').handlers.click({shiftKey:true,altKey:false});
 assert.equal(elements.get('channelSkin').attributes['aria-pressed'],'true');
 assert.equal(elements.get('channelProtected').attributes['aria-pressed'],'false');
 elements.get('dockNative').onclick();
 assert.equal(elements.get('workspace').classList.contains('inspector-docked'),true);
 assert.equal(elements.get('workspace').dataset.inspector,'side');
 assert.equal(elements.get('dockNative').attributes['aria-pressed'],'true');
 elements.get('toolInspect').onclick();
 assert.equal(elements.get('paintMode').value,'off');
 assert.equal(elements.get('toolInspect').attributes['aria-pressed'],'true');

 // Propose structural ROIs -> Inspect candidate -> Lock ROI -> clear stale proposals.
 run("setJob({id:'job-d',revision:2,dimensions:[200,160],label:'D',profile:'luxury_apparel',blend:{skin:0,hair:0,fabric:0,edge_protection:0}});");
 elements.get('inspectNative').onclick();
 finish(pending.slice(-2));await flush();
 assert.equal(elements.get('proposeNativeStructure').disabled,false);
 assert.equal(elements.get('nativeProposalList').hidden,true);
 const proposalRequests=[];
 context.fetch=async(path,options)=>{
  proposalRequests.push([path,options.body&&JSON.parse(options.body)]);
  if(path.endsWith('/propose-structure')){
   return {ok:true,json:async()=>({
    semantic_proof:false,
    proposals:[
     {rectangle:[20,10,40,30],pixels:1200,strong_edges:140,edge_density:0.1167,changed_pixels:90,strong_edge_disagreements:12},
     {rectangle:[100,80,16,16],pixels:256,strong_edges:32,edge_density:0.125,changed_pixels:10,strong_edge_disagreements:1},
    ],
   })};
  }
  if(path.endsWith('/lock-structure')){
   return {ok:true,json:async()=>({...run('current'),revision:3})};
  }
  return {ok:true,json:async()=>({jobs:[],profiles:{},generation_enabled:false})};
 };
 await elements.get('proposeNativeStructure').onclick();
 assert.deepEqual(proposalRequests[0],['/api/regions/jobs/job-d/propose-structure',{expected_revision:2,target:'master',max_proposals:8}]);
 assert.match(elements.get('nativeStructureStatus').textContent,/2 contrast proposals \(heuristic only, not semantic proof\)/);
 assert.equal(elements.get('nativeProposalList').hidden,false);
 assert.equal(elements.get('nativeProposalList').children.length,2);
 const firstItem=elements.get('nativeProposalList').children[0];
 assert.match(firstItem.children[0].textContent,/#1 · x 20–59, y 10–39 \(40 × 30 px\)/);
 firstItem._actions.inspect.onclick();
 assert.equal(elements.get('nativeX').value,'40');
 assert.equal(elements.get('nativeY').value,'25');
 assert.equal(elements.get('nativeSide').value,'64');
 assert.equal(elements.get('nativeProposalList').hidden,false);
 finish(pending.slice(-2));await flush();
 // Unsaved paint disables Lock ROI on proposal cards and blocks direct invocation.
 run("history.done.push({unsaved:true});history.dirty=true;controls();");
 assert.equal(firstItem._actions.lock.disabled,true);
 await firstItem._actions.lock.onclick();
 assert.match(elements.get('error').textContent,/Save or discard unsaved edits/);
 run("history.reset();controls();");
 assert.equal(firstItem._actions.lock.disabled,false);
 await firstItem._actions.lock.onclick();
 assert.deepEqual(proposalRequests[1],['/api/regions/jobs/job-d/lock-structure',{expected_revision:2,regions:[[20,10,40,30]]}]);
 assert.equal(elements.get('nativeProposalList').hidden,true);
 assert.equal(elements.get('nativeProposalList').children.length,0);
 assert.equal(run('current.revision'),3);
 assert.match(elements.get('nativeStructureStatus').textContent,/Proposed ROI locked in revision 3/);

 console.log('Inspector and suggestion DOM contracts passed: paired loading, scales, unsaved state, review gates and stale rejection.');
})().catch(error=>{console.error(error);process.exitCode=1});
