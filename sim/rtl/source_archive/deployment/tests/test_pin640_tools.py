"""Resolution and identity gates for the isolated PIN640 model tools."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import os
import tempfile

from deployment.candidates.pin640.quantize import _graph_metadata, validate_quantization_metadata
from deployment.candidates.pin640.export_graph import validate_domain_class_names
from deployment.candidates.pin640.pack_model import validate_calibration_provenance
from deployment.candidates.pin640.quantize import select_calibration_records

ROOT=Path(__file__).resolve().parents[2]
CANDIDATE=ROOT/'deployment/candidates/pin640'


class Pin640ToolsTests(unittest.TestCase):
    def setUp(self):
        self.graph=dict(domain='pin',class_count=9,classes=[f'PIN_{i}' for i in range(9)],
                        input_shape=[1,3,640,640],input_size=640,reg_max=16,
                        source_class_ids=list(range(9,18)))

    def test_strict_resolution_domain_and_regression_contract(self):
        metadata=_graph_metadata(self.graph,'pin')
        self.assertEqual(metadata['input_size'],640)
        for key,value in (('input_shape',[1,3,416,416]),('input_size',416),
                          ('domain','pcb'),('class_count',18),('reg_max',8),
                          ('source_class_ids',list(range(9)))):
            graph=copy.deepcopy(self.graph);graph[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                _graph_metadata(graph,'pin')
        del self.graph['input_size']
        with self.assertRaises(ValueError):
            _graph_metadata(self.graph,'pin')

    def test_quantization_cannot_be_reused_across_resolution_or_class_order(self):
        metadata=_graph_metadata(self.graph,'pin')
        quantization=dict(metadata,calibration_manifest='fixture.json',
                          calibration_manifest_sha256='a'*64,calibration_ids=['train1'],
                          calibration_domains=['pin'],calibration_split='train')
        validate_quantization_metadata(quantization,metadata)
        for key,value in (('input_size',416),('input_shape',[1,3,416,416]),
                          ('classes',list(reversed(metadata['classes'])))):
            quant=copy.deepcopy(quantization);quant[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_quantization_metadata(quant,metadata)

    def test_empty_pin_class_suffix_is_rejected_before_export(self):
        with self.assertRaises(ValueError):
            validate_domain_class_names(['PIN_']+[f'PIN_{i}' for i in range(1,9)],'pin')

    def test_original416_copy_origins_remain_exact(self):
        origins=json.loads((CANDIDATE/'source_origin.json').read_text(encoding='utf-8'))
        self.assertEqual(len(origins['copies']),45)
        for row in origins['copies']:
            with self.subTest(source=row['source']):
                self.assertEqual(hashlib.sha256((ROOT/row['source']).read_bytes()).hexdigest(),row['source_sha256'])

    def test_tile_wire_math_and_failure_ownership_are_unchanged(self):
        for name in ('v8_tile_abi.c','v8_tile_abi.h','v8_tile_executor.c','v8_tile_executor.h',
                     'v8_tile_board_dma.c','v8_tile_board_dma.h'):
            with self.subTest(name=name):
                self.assertEqual((CANDIDATE/'firmware'/name).read_text(),
                                 (ROOT/'deployment/candidates/tile64/firmware'/name).read_text())

    def test_relative_manifest_resolves_from_project_root_after_fork(self):
        manifest=ROOT/'examples/data/interface_manifest.json'
        self.graph['classes']=json.loads((ROOT/'examples/data/pin_classes.json').read_text(encoding='utf-8'))['names']
        rows,_=select_calibration_records(manifest,'pin',2,self.graph)
        covered=sorted({value for row in rows for value in row['source_class_ids']})
        quant=dict(calibration_split='train',calibration_manifest='examples/data/interface_manifest.json',
                   calibration_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                   calibration_ids=[row['id'] for row in rows],calibration_domains=['pin'],
                   source_global_class_ids_covered=covered,classes_covered=[value-9 for value in covered])
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            try:
                os.chdir(temporary)
                validate_calibration_provenance(quant,'pin',9,list(range(9,18)),self.graph['classes'])
            finally:
                os.chdir(previous)


if __name__=='__main__':
    unittest.main()
