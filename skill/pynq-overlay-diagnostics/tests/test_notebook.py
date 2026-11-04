"""Synthetic notebook tests. No notebook code or hardware is executed."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import inspect_notebook as tool

class NotebookTests(unittest.TestCase):
    def inspect(self,source,outputs=None):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'sample.ipynb'
            path.write_text(json.dumps({'nbformat':4,'cells':[{'cell_type':'code','source':source,'execution_count':100,'outputs':outputs or []}]}),encoding='utf-8')
            return tool.inspect(path)
    def test_never_executes_source(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'must_not_exist'
            self.inspect('from pathlib import Path\nPath('+repr(str(path))+').write_text("executed")\n')
            self.assertFalse(path.exists())
    def test_saved_outputs_cannot_prove_hardware(self):
        r=self.inspect('from pynq import Overlay\nol=Overlay("foo.bit")',[{'output_type':'stream','name':'stdout','text':['PASS 999 FPS']}])
        self.assertFalse(r['hardware_execution']);self.assertFalse(r['saved_outputs_used_as_evidence'])
        self.assertNotIn('999',json.dumps(r))
    def test_default_overlay_detected_as_programming(self):
        r=self.inspect('Overlay("demo.bit")')
        self.assertIn('OVERLAY_MAY_PROGRAM_PL',[x['code'] for x in r['findings']])
    def test_download_false_is_recognized(self):
        r=self.inspect('ol=Overlay("demo.bit", download=False)')
        self.assertNotIn('OVERLAY_MAY_PROGRAM_PL',[x['code'] for x in r['findings']])
    def test_unknown_magic_is_not_python(self):
        r=self.inspect('%%bash\necho something')
        self.assertIn('CELL_NOT_PARSED',[x['code'] for x in r['findings']])
    def test_timeit_body_is_inspected_without_execution(self):
        r=self.inspect('%%timeit\ndma.sendchannel.wait()')
        self.assertEqual(r['pynq_related_calls'][0]['call'],'dma.sendchannel.wait')
    def test_invalid_source_is_unknown(self):
        r=self.inspect('Overlay(')
        self.assertIn('CELL_NOT_PARSED',[x['code'] for x in r['findings']])
    def test_legacy_allocator_is_flagged(self):
        r=self.inspect('x=Xlnk()\na=x.cma_array(shape=(3,4))')
        self.assertIn('LEGACY_ALLOCATION',[x['code'] for x in r['findings']])

if __name__=='__main__':unittest.main()
