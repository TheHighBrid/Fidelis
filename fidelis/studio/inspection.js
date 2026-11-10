/* Native image-pixel crop geometry and stale-safe paired loading. */
(function(root){
'use strict';
function rectangle(dimensions, center, side){
 const [width,height]=dimensions,[cx,cy]=center;
 if(![width,height,cx,cy,side].every(Number.isSafeInteger)||width<1||height<1||side<1||side>512||cx<0||cy<0||cx>=width||cy>=height)throw new Error('Choose an integer pixel inside the original image and a crop size up to 512.');
 const w=Math.min(side,width),h=Math.min(side,height);
 return {x:Math.min(width-w,Math.max(0,cx-Math.floor(w/2))),y:Math.min(height-h,Math.max(0,cy-Math.floor(h/2))),width:w,height:h};
}
function previewPoint(dimensions,box,clientX,clientY){
 if(!(box.width>0&&box.height>0))throw new Error('Overview is not ready.');
 return dimensions.map((size,i)=>Math.max(0,Math.min(size-1,Math.floor((i?(clientY-box.top)/box.height:(clientX-box.left)/box.width)*size))));
}
function urls(job,rect,role){
 if(!['master','texture'].includes(role))throw new Error('Unsupported comparison role');
 return ['base',role].map(value=>`/api/regions/jobs/${encodeURIComponent(job.id)}/crop?`+new URLSearchParams({...rect,role:value,revision:job.revision}));
}
function cssSize(rect,scale){
 if(![1,2].includes(scale))throw new Error('Native scale must be 100% or 200%.');
 return {width:rect.width*scale,height:rect.height*scale};
}
class PairLoader{
 constructor(){this.token=0;}
 invalidate(){this.token++;}
 async load(job,center,side,role,loadImage,commit,fail){
  const token=++this.token;
  try{
   const rect=rectangle(job.dimensions,center,side),paths=urls(job,rect,role);
   const images=await Promise.all(paths.map(loadImage));
   if(token!==this.token)return;
   if(images.some(image=>image.naturalWidth!==rect.width||image.naturalHeight!==rect.height))throw new Error('Native crop dimensions changed; reload the saved job.');
   commit({rect,images,revision:job.revision,role});
  }catch(error){if(token===this.token)fail(error);}
 }
}
const api={rectangle,previewPoint,urls,cssSize,PairLoader};
if(typeof module!=='undefined'&&module.exports)module.exports=api;
else root.FidelisInspection=api;
})(typeof window==='undefined'?this:window);
