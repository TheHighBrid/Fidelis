/* Bounded, immutable undo/redo for unsaved normalized mask strokes. */
(function(root) {
  'use strict';
  class MaskHistory {
    constructor(limit=100) {this.limit=limit;this.done=[];this.undone=[];}
    add(stroke) {
      if(this.done.length>=this.limit) throw new Error(`Save these ${this.limit} strokes before painting more.`);
      if(this.done.reduce((n,s)=>n+s.points.length,0)+stroke.points.length>4000) throw new Error('Save this edit before adding more brush points.');
      this.done.push(JSON.parse(JSON.stringify(stroke)));this.undone=[];
    }
    undo() {if(this.done.length)this.undone.push(this.done.pop());}
    redo() {if(this.undone.length)this.done.push(this.undone.pop());}
    reset() {this.done=[];this.undone=[];}
    strokes() {return JSON.parse(JSON.stringify(this.done));}
    get dirty(){return this.done.length>0;}
  }
  MaskHistory.render=function(layers,width,height,strokes){
    const fields={};for(const name of ['skin','hair','fabric','protected'])fields[name]=layers[name]?new Float32Array(layers[name]):new Float32Array(width*height);
    for(const stroke of strokes){
      const amount=new Float32Array(width*height),radius=stroke.radius*Math.min(width,height),points=stroke.points.map(([x,y])=>[x*width-.5,y*height-.5]);
      const pairs=points.length===1?[[points[0],points[0]]]:points.slice(1).map((point,i)=>[points[i],point]);
      for(const [[ax,ay],[bx,by]] of pairs){
        const dx=bx-ax,dy=by-ay,den=Math.max(dx*dx+dy*dy,1e-12);
        const x0=Math.max(0,Math.floor(Math.min(ax,bx)-radius)),x1=Math.min(width,Math.ceil(Math.max(ax,bx)+radius)+1);
        const y0=Math.max(0,Math.floor(Math.min(ay,by)-radius)),y1=Math.min(height,Math.ceil(Math.max(ay,by)+radius)+1);
        for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){
          const t=Math.max(0,Math.min(1,((x-ax)*dx+(y-ay)*dy)/den));
          const d=Math.hypot(x-ax-t*dx,y-ay-t*dy)/radius;
          const a=(stroke.hardness===1?(d<=1?1:0):Math.max(0,Math.min(1,(1-d)/(1-stroke.hardness))))*stroke.opacity;
          const i=y*width+x;amount[i]=Math.max(amount[i],a);
        }
      }
      for(let i=0;i<amount.length;i++){const a=amount[i];if(!a)continue;const target=fields[stroke.layer];if(stroke.mode==='erase')target[i]*=1-a;else {target[i]+=(1-target[i])*a;if(stroke.layer!=='protected')for(const other of ['skin','hair','fabric'])if(other!==stroke.layer)fields[other][i]*=1-a;}}
    }
    return fields;
  };
  if(typeof module!=='undefined'&&module.exports)module.exports=MaskHistory;
  else root.FidelisMaskHistory=MaskHistory;
})(typeof window!=='undefined'?window:{});
