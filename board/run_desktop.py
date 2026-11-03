"""Start the delivered Z100 workbench using only files in this package."""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODEL_SHA = '65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c'
CLASS_SHA = 'd194f74601c88214c24506a910c1bac71c87ce0be7ddda213d3eb00684d43754'


def configuration():
    path = ROOT / 'data/pin_epoch200_int8.v8p'
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != MODEL_SHA:
        raise ValueError('The delivered model hash does not match the accepted model.')
    magic, version, size, crc, nodes, arena, count, resolution = struct.unpack('<4s7I', data[:32])
    if (magic, version, count, resolution) != (b'V8PK', 1, 9, 640) or len(data) != size + 32 or zlib.crc32(data[32:]) != crc:
        raise ValueError('Invalid model package.')
    classes = json.loads((ROOT/'data/model/classes.json').read_text(encoding='utf-8'))['names']
    digest = hashlib.sha256(json.dumps(classes, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if digest != CLASS_SHA:
        raise ValueError('The class order does not match the model.')
    return path, classes


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='192.168.10.2')
    parser.add_argument('--port', type=int, default=5001)
    parser.add_argument('--local-address', default=None, help='optional local IPv4 bind; configure for your computer')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--history-dir', type=Path, default=ROOT.parent/'repro_output/desktop_history',
                        help='history directory outside the sealed package')
    parser.add_argument('--check', action='store_true', help='model identity only; no window or network')
    args=parser.parse_args()
    history=args.history_dir.expanduser().resolve()
    if history == ROOT or history.is_relative_to(ROOT):
        parser.error('--history-dir must be outside the package')
    model,names=configuration()
    if args.check:
        print(json.dumps(dict(status='PASS_PORTABLE_DESKTOP_CONFIG', model='data/pin_epoch200_int8.v8p',
                             model_sha256=MODEL_SHA, classes_sha256=CLASS_SHA, class_count=len(names),
                             input_size=640, network_used=False),indent=2))
        return 0
    import tkinter as tk
    from src.desktop import app as ui
    ui.HISTORY_DIR=history
    root=tk.Tk()
    app=ui.App(root,host=args.host,port=args.port,model=model,names=names,allow_host_reference=False,
               timeout=args.timeout,local_address=args.local_address)
    app.playback_delay.set(0)
    root.title('Z100 光电缺陷检测 · PIN9 / 640')
    root.mainloop()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
