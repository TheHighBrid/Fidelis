"""Explicit benchmark inventory and unsigned freeze receipts, separate from legacy discovery.

No synthetic gap filling, inferred consent, automatic split assignment or network IO.
"""
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from PIL import Image

CATEGORIES = ('portrait', 'model_apparel', 'textile', 'macro', 'packshot_edge')
ROI_TYPES = {'skin','hair','fabric','logo','text','seam','hardware','background','highlight','shadow','identity','alpha_boundary'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def local_path(root, value):
    if not isinstance(value,str) or not value or Path(value).is_absolute():
        raise ValueError('Expected a nonempty root-relative path')
    root=Path(root).resolve();path=(root/value).resolve()
    if not path.is_relative_to(root):raise ValueError('Path escapes asset root')
    return path


def inspect_image(path):
    if path.stat().st_size > 200*1024**2:raise ValueError('Source exceeds 200 MiB')
    with Image.open(path) as image:
        if image.width*image.height>40_000_000 or getattr(image,'n_frames',1)!=1:
            raise ValueError('Source exceeds 40 MP or contains multiple frames')
        image.load()
        h=hashlib.sha256(f'{image.width}x{image.height}:RGBA'.encode())
        for y in range(0,image.height,64):
            h.update(image.crop((0,y,image.width,min(image.height,y+64))).convert('RGBA').tobytes())
        return {'sha256':file_hash(path),'pixel_sha256':h.hexdigest(),
                'dimensions':[image.width,image.height],'mode':image.mode,'format':image.format,
                'icc_present':bool(image.info.get('icc_profile')),'orientation':image.getexif().get(274,1)}


def validate_design(protocol, slots):
    if not isinstance(protocol,dict) or not isinstance(slots,dict):raise ValueError('Protocol and slot plan must be objects')
    if protocol.get('schema_version')!=1 or protocol.get('categories')!={key:12 for key in CATEGORIES}:
        raise ValueError('Protocol v1 requires five declared categories with 12 cases each')
    if protocol.get('split')!={'calibration':30,'held_out':30}:
        raise ValueError('Protocol v1 requires a 30/30 split')
    if slots.get('schema_version')!=1 or slots.get('protocol_sha256')!=digest(protocol):
        raise ValueError('Slot plan/protocol hash mismatch')
    rows=slots.get('slots',[])
    if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise ValueError('Slot records must be objects')
    if len(rows)!=60 or len({r['id'] for r in rows})!=60:raise ValueError('Exactly 60 unique slots required')
    counts=Counter((r['category'],r['split']) for r in rows)
    if counts!=Counter({(cat,split):6 for cat in CATEGORIES for split in ('calibration','held_out')}):
        raise ValueError('Each category needs six calibration and six held-out slots')
    return {row['id']:row for row in rows}


def audit(manifest, protocol, slots, root):
    design=validate_design(protocol,slots)
    if not isinstance(manifest,dict):raise ValueError('Manifest must be an object')
    if manifest.get('schema_version')!=1 or manifest.get('protocol_sha256')!=digest(protocol) or manifest.get('slots_sha256')!=digest(slots):
        raise ValueError('Manifest schema/design hash mismatch')
    cases=manifest.get('cases')
    if not isinstance(cases,list) or len(cases)>1000:raise ValueError('Expected at most 1000 inventory records')
    ids=set();claimed={};groups={};hashes={};pixels={};rows=[];eligible=[]
    for case in cases:
        if not isinstance(case,dict):raise ValueError('Case must be an object')
        case_id=case.get('id')
        if not isinstance(case_id,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}',case_id) or case_id in ids:
            raise ValueError('Missing/duplicate/invalid case ID')
        ids.add(case_id)
        role=case.get('role')
        if role not in ('regression','production'):raise ValueError('Declare regression or production role')
        slot_id=case.get('slot_id');issues=[];observed=None
        if role=='production':
            if slot_id not in design or slot_id in claimed:raise ValueError('Unknown/duplicate production slot')
            claimed[slot_id]=case_id
            if case.get('category')!=design[slot_id]['category']:raise ValueError('Case/slot category mismatch')
        elif slot_id is not None:raise ValueError('Regression assets cannot fill production slots')
        if case.get('category') not in CATEGORIES:raise ValueError('Unknown category')
        source=case.get('source')
        if not isinstance(source,dict):raise ValueError('Source inventory is required')
        try:
            path=local_path(root,source.get('path'))
            if not path.is_file():issues.append('source_missing')
            else:
                observed=inspect_image(path)
                if any(source.get(key)!=value for key,value in observed.items()):issues.append('source_fingerprint_changed')
        except (OSError,ValueError,Image.DecompressionBombError):issues.append('source_invalid_or_unavailable')
        if case.get('source_kind')!='photograph':issues.append('not_a_photographic_production_case')
        rights=case.get('rights',{})
        if not isinstance(rights,dict):raise ValueError('Rights must be an object')
        if rights.get('status') not in ('unknown','approved','denied'):raise ValueError('Unknown rights status')
        if rights.get('status')!='approved' or rights.get('local_evaluation') is not True:issues.append('local_rights_unapproved')
        if rights.get('subject_consent') not in ('approved','not_required'):issues.append('subject_consent_unresolved')
        if rights.get('remote_processing') not in ('unknown','allowed','denied'):raise ValueError('Declare remote processing permission separately')
        try:
            evidence=local_path(root,rights.get('evidence_path'))
            if not evidence.is_file() or file_hash(evidence)!=rights.get('evidence_sha256'):issues.append('rights_evidence_missing_or_changed')
        except (ValueError,OSError):issues.append('rights_evidence_missing_or_changed')
        if not all(isinstance(rights.get(k),str) and rights[k].strip() for k in ('reviewed_by','reviewed_at','basis')):
            issues.append('rights_review_incomplete')
        group=case.get('leakage_group')
        if not isinstance(group,str) or not group.strip():issues.append('leakage_group_unresolved')
        target=case.get('target_dimensions')
        if not isinstance(target,list) or len(target)!=2 or any(type(v) is not int or not 0<v<=32768 for v in target):
            issues.append('target_dimensions_missing_or_invalid')
        if case.get('expected_behavior') not in ('enhance','reject_unsupported_input'):issues.append('expected_behavior_unresolved')
        rois=case.get('rois')
        if not isinstance(rois,list):raise ValueError('ROIs must be a list')
        roi_ids=set()
        if not rois:issues.append('critical_rois_unreviewed')
        for roi in rois:
            if not isinstance(roi,dict):raise ValueError('ROI must be an object')
            rid=roi.get('id');rect=roi.get('rect');kind=roi.get('kind')
            if not isinstance(rid,str) or not rid or rid in roi_ids:raise ValueError('Missing/duplicate ROI ID')
            roi_ids.add(rid)
            if kind not in ROI_TYPES or roi.get('policy') not in ('preserve','texture_allowed'):
                raise ValueError('Invalid ROI type/policy')
            if not isinstance(rect,list) or len(rect)!=4 or any(type(v) is not int for v in rect):raise ValueError('ROI rect must contain four integers')
            x,y,w,h=rect
            if x<0 or y<0 or w<1 or h<1 or (observed and (x+w>observed['dimensions'][0] or y+h>observed['dimensions'][1])):
                issues.append('roi_outside_source')
        known_text=case.get('known_text')
        if not isinstance(known_text,list):raise ValueError('known_text must be a list')
        if case.get('text_review')!='completed':issues.append('text_review_incomplete')
        transcripts=set()
        for entry in known_text:
            if not isinstance(entry,dict):raise ValueError('Text transcript must be an object')
            if entry.get('roi_id') not in roi_ids or entry.get('roi_id') in transcripts or not isinstance(entry.get('text'),str) or not entry['text'].strip():
                raise ValueError('Known text requires a unique valid ROI and nonempty transcript')
            transcripts.add(entry['roi_id'])
        if any(roi['kind']=='text' and roi['id'] not in transcripts for roi in rois):issues.append('text_roi_transcript_missing')
        if role=='production':
            split=design[slot_id]['split']
            if group:
                if group in groups and groups[group]!=split:issues.append('group_crosses_splits')
                groups[group]=split
            if observed:
                for field,seen in (('sha256',hashes),('pixel_sha256',pixels)):
                    if observed[field] in seen:issues.append('duplicate_'+field)
                    seen[observed[field]]=case_id
            if not issues:eligible.append(slot_id)
        rows.append({'id':case_id,'role':role,'slot_id':slot_id,'available':observed is not None,
                     'eligible':role=='production' and not issues,'blockers':sorted(set(issues)),
                     'observed':observed})
    missing=sorted(set(design)-set(claimed));unready=sorted(set(claimed)-set(eligible))
    # Any duplicate/group conflict blocks the entire freeze, including the first member.
    review=manifest.get('coverage_review',{})
    global_blockers=[]
    if not isinstance(review,dict) or review.get('status')!='approved' or not all(isinstance(review.get(k),str) and review[k].strip() for k in ('reviewed_by','reviewed_at')):
        global_blockers.append('coverage_review_unapproved')
    try:
        evidence=local_path(root,review.get('evidence_path') if isinstance(review,dict) else None)
        if not evidence.is_file() or file_hash(evidence)!=review.get('evidence_sha256'):global_blockers.append('coverage_evidence_missing_or_changed')
    except (ValueError,OSError):global_blockers.append('coverage_evidence_missing_or_changed')
    ready=len(eligible)==60 and not missing and not unready and not global_blockers
    return {'schema_version':1,'production_ready':ready,'production_target':60,
            'production_eligible':len(eligible),'regression_available':sum(r['role']=='regression' and r['available'] for r in rows),
            'missing_slots':missing,'unready_slots':unready,'global_blockers':global_blockers,'cases':rows,
            'coverage':{cat:{split:sum(s in eligible and row['category']==cat and row['split']==split for s,row in design.items())
                             for split in ('calibration','held_out')} for cat in CATEGORIES},
            'permissions_are_declarations_not_legal_verification':True}


def freeze(manifest, protocol, slots, root):
    report=audit(manifest,protocol,slots,root)
    if not report['production_ready']:raise ValueError('Corpus is not ready: complete rights, fingerprints, ROIs, targets and independent split coverage first')
    record={'schema_version':1,'record_type':'unsigned_corpus_lock','manifest':copy.deepcopy(manifest),'protocol':copy.deepcopy(protocol),'slots':copy.deepcopy(slots),
            'manifest_sha256':digest(manifest),'protocol_sha256':digest(protocol),'slots_sha256':digest(slots)}
    return {**record,'lock_sha256':digest(record)}


def verify(record, root):
    if not isinstance(record,dict):raise ValueError('Corpus lock must be an object')
    if record.get('schema_version')!=1 or record.get('record_type')!='unsigned_corpus_lock':raise ValueError('Invalid corpus lock')
    payload={k:v for k,v in record.items() if k!='lock_sha256'}
    if record.get('lock_sha256')!=digest(payload):raise ValueError('Corpus lock digest changed')
    for key in ('manifest','protocol','slots'):
        if record.get(key+'_sha256')!=digest(record[key]):raise ValueError('Snapshot digest mismatch')
    report=audit(record['manifest'],record['protocol'],record['slots'],root)
    if not report['production_ready']:raise ValueError('Locked corpus no longer matches its assets/permissions')
    return report
