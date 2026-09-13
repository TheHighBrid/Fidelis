#!/usr/bin/env python3
import ast
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


repo_root = Path(__file__).resolve().parents[1]
notebook = json.loads((repo_root / 'notebooks/Fidelis_VOSR2_Colab.ipynb').read_text())
source = next(
    ''.join(cell['source'])
    for cell in notebook['cells']
    if cell['cell_type'] == 'code' and 'def fidelity_finish' in ''.join(cell['source'])
)
tree = ast.parse(source)
helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {'_blur', 'fidelity_finish'}]
module = ast.Module(body=helpers, type_ignores=[])
namespace = {'np': np, 'Image': Image, 'ImageFilter': ImageFilter}
exec(compile(module, 'fidelity_finish', 'exec'), namespace)
finish = namespace['fidelity_finish']


base = Image.new('RGB', (64, 48), (128, 128, 128))
same = Image.new('RGB', (256, 192), (128, 128, 128))
unchanged = np.asarray(finish(base, same), dtype=np.int16)
assert unchanged.shape == (96, 128, 3)
assert np.max(np.abs(unchanged - 128)) <= 1

# A strong edge found only in the generated candidate must not be copied at
# full strength. This is the failure class that creates fake seams and faces.
invented = np.full((192, 256, 3), 128, dtype=np.uint8)
invented[:, 120:136] = 0
protected = np.asarray(finish(base, Image.fromarray(invented)), dtype=np.int16)
assert protected[:, 61:67].mean() > 105

print('Fidelity finishing tests passed.')
