// DOM-contract fixture, not a browser/rendering or target-device acceptance test.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const inspection=require('../fidelis/studio/inspection.js');
const html=fs.readFileSync(process.argv[2],'utf8');
const elements=new Map();
class Element{
 constructor(){this.children=[];this.style={};this.dataset={};this.handlers={};this.value='';this.hidden=false;this.disabled=false;this.options=[];this.classList={toggle(){}};this.attributes={};this.tagName='DIV';}
 set id(value){this._id=value;elements.set(value,this);}
 get id(){return this._id;}
 addEventListener(type,handler){this.handlers[type]=handler;}
 removeAttribute(key){delete this.attributes[key];}
 setAttribute(key,value){this.attributes[key]=value;}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=children;}
 scrollIntoView(){}
 getBoundingClientRect(){return {left:0,top:0,width:800,height:600};}
 getContext(){return {clearRect(){},putImageData(){},createImageData(){return {data:new Uint8ClampedArray(0)}}};}
}
for(const match of html.matchAll(/id="([^"]+)"/g))elements.set(match[1],new Element());
for(const [id,value] of Object.entries({nativeZoom:'1',nativeRole:'master',nativeSide:'256',nativeSplit:'50',paintMode:'off'}))elements.get(id).value=value;
elements.get('nativePanel').hidden=true;
const pending=[];
class FixtureImage extends Element{
 set src(value){this.url=value;pending.push(this);}
}
class History{constructor(){this.done=[];this.undone=[];this.dirty=false;}reset(){this.done=[];this.undone=[];this.dirty=false;}strokes(){return []}}
const context={console,URLSearchParams,Image:FixtureImage,FidelisInspection:inspection,FidelisMaskHistory:History,
 document:{getElementById:id=>elements.get(id),createElement:()=>new Element(),activeElement:{tagName:'DIV'}},
 window:{addEventListener(){}},setTimeout(){},requestAnimationFrame(){},confirm:()=>true,
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
 console.log('Inspector and suggestion DOM contracts passed: paired loading, scales, unsaved state, review gates and stale rejection.');
})().catch(error=>{console.error(error);process.exitCode=1});
