"""Verify the first successful 7Z100 frame without any board access."""
from pathlib import Path
import hashlib
import json
import struct
import zlib

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'board/baseline'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    identity=json.loads((BASE/'baseline_identity.json').read_text(encoding='utf-8'))
    for entry in identity['files']:
        path=(BASE/entry['path']).resolve()
        assert path.is_relative_to(BASE) and path.stat().st_size==entry['bytes']
        assert sha(path)==entry['sha256'],entry['path']
    for entry in identity['artifact_hashes_recomputed']:
        path=(ROOT/entry['path']).resolve()
        assert path.is_relative_to(ROOT) and path.stat().st_size==entry['bytes']
        assert sha(path)==entry['sha256'],entry['path']
    raw=json.loads((BASE/'result.json').read_text(encoding='utf-8'))
    summary=json.loads((BASE/'first_frame_summary.json').read_text(encoding='utf-8'))
    assert raw['status']=='PASS_ONE_PHYSICAL_FULL_MODEL_FRAME_613200_BYTES_EXACT'
    assert raw['raw_head_mismatch_count']==summary['raw_head_mismatch_count']==0
    heads=(BASE/'raw_heads_padded.bin').read_bytes()
    assert hashlib.sha256(heads[:613200]).hexdigest()==raw['raw_head_sha256']==raw['expected_head_sha256']
    assert raw['elf_sha256']==sha(BASE/'artifacts/full_model_jtag.elf')
    milliseconds=raw['pipeline_ticks']['total_ticks']/summary['timer_hz_from_matched_bsp']*1000
    assert abs(milliseconds-summary['phase_milliseconds']['total_ticks'])<1e-9
    assert summary['validation_images']==1 and summary['sustained_fps_measured'] is False
    blob=(ROOT/'data/baseline/epoch108_int8.v8p').read_bytes()
    magic,version,size,crc,nodes,arena,classes,resolution=struct.unpack('<4s7I',blob[:32])
    assert (magic,version,nodes,classes,resolution)==(b'V8PK',1,163,9,640)
    assert len(blob)==size+32 and zlib.crc32(blob[32:])==crc
    print(json.dumps(dict(status='PASS_FIRST_7Z100_BASELINE_FILES_AND_TIMING',model_epoch=108,
                         board_function_single_frame_ms=milliseconds,sustained_fps_measured=False,
                         board_access=False,scope='Historical evidence integrity and arithmetic; no new inference'),indent=2))

if __name__=='__main__':main()
