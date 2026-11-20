"""Native brush rasterization, persisted editing and browser history parity."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import numpy as np

from fidelis.studio.brush import apply_stripe, coverage, validate_strokes
from fidelis.studio.store import JobStore, RevisionConflict
from fidelis.postprocess.regions import RegionBlend


def stroke(layer='skin',mode='paint',**overrides):
    return dict(layer=layer,mode=mode,radius=.2,hardness=.6,opacity=1,
                points=[[.25,.5],[.75,.5]],**overrides)


class BrushTests(unittest.TestCase):
    def test_stripes_match_full_frame_including_edges(self):
        s=stroke()
        full=coverage(s,41,29,0,29)
        parts=np.concatenate([coverage(s,41,29,y,min(29,y+3)) for y in range(0,29,3)])
        np.testing.assert_array_equal(full,parts)
        self.assertGreater(full[14,20],.9)
        self.assertEqual(full[0,0],0)

    def test_one_stroke_overlap_does_not_multiply_opacity(self):
        s=stroke();s.update(opacity=.3,hardness=1)
        s['points']=[[.25,.5],[.75,.5],[.25,.5]]
        self.assertLessEqual(float(coverage(s,41,29,0,29).max()),.30001)

    def test_protection_survives_material_paint_and_layer_specific_erase(self):
        fields={name:np.zeros((20,20),np.float32) for name in ('skin','hair','fabric','protected','confidence')}
        fields['protected'][:]=1
        apply_stripe(fields,[stroke(),stroke('skin','erase')],20,20,0,20)
        np.testing.assert_array_equal(fields['protected'],1)
        self.assertGreater(fields['confidence'].max(),0)
        self.assertEqual(fields['skin'][10,10],0)

    def test_validation_rejects_invalid_and_unbounded_input(self):
        for change in ({'radius':float('nan')},{'radius':0},{'layer':'metal'},{'points':[[2,0]]},
                       {'points':[[True,0]]},{'mode':'clear-everything'}):
            s=stroke();s.update(change)
            with self.assertRaises(ValueError):validate_strokes([s])
        with self.assertRaises(ValueError):validate_strokes([stroke()]*101)

    def test_save_reopen_masks_and_hard_protection(self):
        with tempfile.TemporaryDirectory() as root:
            base=np.full((30,40,3),60,np.uint8)
            texture=np.full_like(base,240)
            protected=np.zeros((30,40),np.float32);protected[:,19:22]=1
            store=JobStore(root,workspace_budget=40*256*2)
            job=store.create(base,texture,masks={'protected':protected})
            updated=store.reblend(job['id'],expected_revision=1,blend=RegionBlend(1),strokes=[stroke()])
            self.assertEqual(updated['revision'],2)
            reopened=JobStore(root)
            with reopened.open_array(job['id'],'master') as output:
                np.testing.assert_array_equal(output[:,19:22],base[:,19:22])
                self.assertGreater(int(output[15,12,0]),60)
            self.assertEqual(len(reopened.get(job['id'])['last_mask_edit']['strokes']),1)
            with self.assertRaises(RevisionConflict):
                reopened.reblend(job['id'],expected_revision=1,blend=RegionBlend(),strokes=[stroke()])

    @unittest.skipUnless(shutil.which('node'),'Node unavailable')
    def test_browser_history_and_rasterization_match_native_math(self):
        editor=Path(__file__).resolve().parents[1]/'fidelis/studio/editor.js'
        strokes=[stroke(),stroke('protected'),stroke('skin','erase')]
        code='''const H=require(process.argv[1]);const list=JSON.parse(process.argv[2]);
const h=new H();h.add(list[0]);list[0].points[0][0]=0;h.undo();h.redo();
if(h.strokes()[0].points[0][0]!==.25)throw Error('History mutated');
h.undo();h.add(list[1]);if(h.undone.length)throw Error('Redo branch retained');
h.reset();if(h.dirty)throw Error('Reset failed');
const s=JSON.parse(process.argv[3]);const fields=H.render({},24,20,s);
console.log(JSON.stringify(Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,Array.from(v)]))));'''
        result=subprocess.run(['node','-e',code,str(editor),json.dumps(strokes),json.dumps(strokes)],
                              capture_output=True,text=True,check=True)
        fields={name:np.zeros((20,24),np.float32) for name in ('skin','hair','fabric','protected','confidence')}
        apply_stripe(fields,strokes,24,20,0,20)
        for name,values in json.loads(result.stdout).items():
            np.testing.assert_allclose(np.array(values).reshape(20,24),fields[name],atol=2e-6)


if __name__=='__main__':unittest.main()
