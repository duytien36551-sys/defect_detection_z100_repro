"""Verify delivered model files and V8PK contract; standard library only."""
from pathlib import Path
import hashlib
import json
import struct
import zlib

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root/'report/current_model_manifest.json').read_text(encoding='utf-8'))
for entry in manifest['files']:
    path = (root/entry['path']).resolve()
    assert path.is_relative_to(root), entry['path']
    blob = path.read_bytes()
    assert len(blob) == entry['bytes'], f"Size mismatch: {entry['path']}"
    assert hashlib.sha256(blob).hexdigest() == entry['sha256'], f"SHA mismatch: {entry['path']}"
blob = (root/'data/pin_epoch200_int8.v8p').read_bytes()
magic, version, size, crc, nodes, arena, classes, resolution = struct.unpack('<4s7I', blob[:32])
assert (magic,version,classes,resolution) == (b'V8PK',1,9,640)
assert len(blob) == size+32 and zlib.crc32(blob[32:]) == crc
metadata = json.loads((root/'data/model/package.json').read_text(encoding='utf-8'))
names = json.loads((root/'data/model/classes.json').read_text(encoding='utf-8'))
assert metadata['classes'] == names['names'] and len(set(names['names'])) == 9
digest = hashlib.sha256(json.dumps(names['names'],ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
assert digest == names['classes_sha256'] == 'd194f74601c88214c24506a910c1bac71c87ce0be7ddda213d3eb00684d43754'
assert metadata['protocol'] == names['protocol'] == manifest['protocol']
assert metadata['model_sha256'] == hashlib.sha256((root/'data/pin_epoch200.pt').read_bytes()).hexdigest()
assert (metadata['node_count'],metadata['arena_bytes'],metadata['parameter_bytes'],metadata['parameter_crc32']) == (nodes,arena,size,crc)
assert (root/'data/reference/input_rgb.bin').stat().st_size == 1228800
assert (root/'data/reference/expected_heads_int8.bin').stat().st_size == 613200
result = dict(status='PASS_MODEL_FILES_AND_CONTRACT', verified_files=len(manifest['files']),
              selected_epoch=200, class_count=9, input_size=640,
              board_access=False, inference_run=False,
              scope='SHA256, byte lengths, V8PK CRC/header, package and ordered-class identity; not accuracy or hardware validation')
print(json.dumps(result,ensure_ascii=False,indent=2))
