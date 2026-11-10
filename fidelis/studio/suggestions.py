"""Source-bound imported semantic probability proposals, not a segmentation model."""
import hashlib
import io
import json
import re
import zipfile

import numpy as np

FIELDS=('skin','hair','fabric','protected','confidence')
REGIONS=('unknown','skin','hair','fabric','protected')
MAX_SCORE_BYTES=64*1024**2


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def decode_scores(raw):
    """Inspect NPY headers/expanded size before loading an untrusted NPZ."""
    if len(raw)>MAX_SCORE_BYTES:raise ValueError('Score archive exceeds 64 MiB')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if archive.namelist()!=['probabilities.npy']:raise ValueError('Expected only probabilities.npy')
        entry=archive.infolist()[0]
        if entry.file_size>MAX_SCORE_BYTES:raise ValueError('Expanded probabilities exceed 64 MiB')
        with archive.open(entry) as stream:
            version=np.lib.format.read_magic(stream)
            if version!=(1,0):raise ValueError('Use NPY v1 float32 probability data')
            shape,fortran,dtype=np.lib.format.read_array_header_1_0(stream)
            if len(shape)!=3 or not 2<=shape[0]<=32 or not 1<=shape[1]<=1024 or not 1<=shape[2]<=1024 or dtype!=np.dtype('float32') or fortran:
                raise ValueError('Expected CxHxW float32, 2..32 classes, score sides up to 1024')
            if int(np.prod(shape))*4>entry.file_size:raise ValueError('Truncated probability array')
        with np.load(io.BytesIO(raw),allow_pickle=False) as data:
            return np.array(data['probabilities'],copy=True)


def build_suggestion(scores, receipt, *, base_sha256, dimensions, threshold=.90, margin=.15, boundary=1):
    if not isinstance(receipt,dict) or receipt.get('schema_version')!=1:
        raise ValueError('Expected probability receipt schema_version 1')
    if len(json.dumps(receipt,allow_nan=False).encode())>64*1024:raise ValueError('Receipt exceeds 64 KiB')
    if receipt.get('base_artifact_sha256')!=base_sha256 or receipt.get('input_dimensions')!=list(dimensions):
        raise ValueError('Probabilities belong to a different base image/grid')
    if receipt.get('transform')!='full_frame_resize_no_crop_no_rotation':
        raise ValueError('Declare the full-frame score-to-input transform; crops/warps are unsupported')
    model=receipt.get('model');labels=receipt.get('labels')
    if not isinstance(model,dict) or not all(isinstance(model.get(k),str) and model[k].strip() for k in ('id','revision','terms_reference')):
        raise ValueError('Record actual model ID, revision and terms reference')
    if not isinstance(model.get('weights_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',model['weights_sha256']):
        raise ValueError('Record the actual model weight hash')
    scores=np.asarray(scores)
    if scores.dtype!=np.float32 or scores.ndim!=3 or not 2<=scores.shape[0]<=32 or max(scores.shape[1:])>1024 or min(scores.shape[1:])<1 or scores.nbytes>MAX_SCORE_BYTES:
        raise ValueError('Invalid bounded CxHxW float32 probability tensor')
    if not isinstance(labels,list) or len(labels)!=scores.shape[0] or any(not isinstance(label,dict) or not isinstance(label.get('name'),str) or not label['name'].strip() or label.get('region') not in REGIONS for label in labels):
        raise ValueError('Every actual class label needs an explicit routing region')
    if len({label['name'] for label in labels})!=len(labels):raise ValueError('Class names must be unique')
    if not np.all(np.isfinite(scores)) or np.any(scores<0) or np.any(scores>1) or not np.allclose(scores.sum(axis=0),1,atol=.001,rtol=0):
        raise ValueError('Supply complete normalized probabilities, not logits or partial class scores')
    if type(threshold) not in (float,int) or not .5<=threshold<=1 or type(margin) not in (float,int) or not 0<=margin<=1 or not np.isfinite(threshold+margin) or type(boundary) is not int or not 0<=boundary<=8:
        raise ValueError('Invalid confidence, ambiguity or boundary settings')
    mass=np.zeros((len(REGIONS),*scores.shape[1:]),np.float32)
    for index,label in enumerate(labels):mass[REGIONS.index(label['region'])]+=scores[index]
    winner=np.argmax(mass,axis=0);top=np.minimum(1,np.max(mass,axis=0));second=np.partition(mass,-2,axis=0)[-2]
    accepted=(winner!=0)&(top>=threshold)&((top-second)>=margin)
    # Erode permission at class changes/uncertain boundaries, including frame edges.
    if boundary:
        valid=accepted.copy();height,width=accepted.shape
        pad=np.pad(np.where(accepted,winner,-1),boundary,constant_values=-1)
        for dy in range(2*boundary+1):
            for dx in range(2*boundary+1):valid &= pad[dy:dy+height,dx:dx+width]==winner
        accepted=valid
    masks={name:((winner==REGIONS.index(name))&accepted).astype(np.float32) for name in FIELDS if name!='confidence'}
    masks['confidence']=np.where(accepted&(winner!=4),top,0).astype(np.float32)
    record={'schema_version':1,'origin':'imported_class_probabilities','receipt':receipt,
            'receipt_sha256':canonical_hash(receipt),'probabilities_sha256':hashlib.sha256(scores.tobytes(order='C')).hexdigest(),
            'score_dimensions':[scores.shape[2],scores.shape[1]],'target_dimensions':list(dimensions),
            'threshold':float(threshold),'margin':float(margin),'boundary_score_pixels':boundary,
            'score_acceptance_fraction':float(np.mean(accepted)),
            'resampling':'nearest_full_frame','live_segmentation_quality_verified':False,
            'confidence_is_calibrated':False,'labels_and_terms_independently_verified':False}
    # JSON-freeze untrusted caller metadata before any persistence.
    return masks,json.loads(json.dumps(record,allow_nan=False))


def upsample_stripe(low_masks,width,height,start,end):
    """Explicit whole-frame nearest mapping; no full-size class tensor allocation."""
    low_h,low_w=low_masks['confidence'].shape
    xs=np.minimum(np.arange(width,dtype=np.int64)*low_w//width,low_w-1)
    ys=np.minimum(np.arange(start,end,dtype=np.int64)*low_h//height,low_h-1)
    return {name:mask[ys[:,None],xs[None,:]] for name,mask in low_masks.items()}


def fill_unclassified(existing,proposal):
    shape=proposal['confidence'].shape
    current={name:np.array(existing.get(name,np.zeros(shape,np.float32)),copy=True) for name in FIELDS}
    available=np.ones(shape,bool)
    for name,mask in existing.items():
        if name in FIELDS or name=='edge_guard':available &= mask==0
    for name in FIELDS:current[name][available]=proposal[name][available]
    return current
