#!/usr/bin/env python3
"""Offline PYNQ overlay and AXI simple-DMA contract checks. No PYNQ import."""
import argparse
import hashlib
import json
import math
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_XML = 32 * 1024 * 1024
DTYPE_BYTES = {'uint8': 1, 'int8': 1, 'uint16': 2, 'int16': 2, 'uint32': 4, 'int32': 4, 'float32': 4, 'uint64': 8, 'int64': 8, 'float64': 8}

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()

def integer(value, label, minimum=0):
    if isinstance(value, bool):
        raise ValueError(label + ' must be an integer')
    if isinstance(value, str):
        value = int(value, 0) if value.lower().startswith('0x') else int(value)
    if not isinstance(value, int) or value < minimum:
        raise ValueError(label + ' must be an integer >= ' + str(minimum))
    return value

def json_unique(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError('Duplicate JSON field: ' + k)
        result[k] = v
    return result

def load_config(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=json_unique)
    if not isinstance(data, dict) or data.get('schema') != 'pynq-overlay-contract-v1':
        raise ValueError('Expected schema pynq-overlay-contract-v1')
    unknown = set(data) - {'schema', 'name', 'expected_device', 'required_ips', 'dma', 'scope_note'}
    if unknown:
        raise ValueError('Unknown contract fields: ' + ', '.join(sorted(unknown)))
    return data

def read_metadata(path, member=None):
    path = Path(path)
    if path.suffix.lower() in {'.xsa', '.zip'}:
        with zipfile.ZipFile(path) as archive:
            candidates = [x for x in archive.infolist() if x.filename.lower().endswith('.hwh')]
            if member is not None:
                candidates = [x for x in candidates if x.filename == member]
            if len(candidates) != 1:
                raise ValueError('Select exactly one HWH using --member; candidates=' + str([x.filename for x in candidates]))
            entry = candidates[0]
            if entry.file_size > MAX_XML:
                raise ValueError('HWH exceeds 32 MiB limit')
            raw = archive.read(entry)
            selected = entry.filename
    else:
        if member is not None:
            raise ValueError('--member requires an XSA/ZIP')
        if path.stat().st_size > MAX_XML:
            raise ValueError('HWH exceeds 32 MiB limit')
        raw = path.read_bytes()
        selected = None
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('DTD/entity declarations are not supported')
    root = ET.fromstring(raw)
    for e in root.iter():
        e.tag = e.tag.split('}')[-1]
    info = next(root.iter('SYSTEMINFO'), None)
    device = info.get('DEVICE') if info is not None else None
    ips = {}
    for module in root.iter('MODULE'):
        name = (module.get('FULLNAME') or module.get('INSTANCE') or '').strip('/')
        if not name:
            continue
        if name in ips:
            raise ValueError('Duplicate IP path: ' + name)
        parameters = {}
        for parameter in module.findall('./PARAMETERS/PARAMETER'):
            key = parameter.get('NAME', '').lower()
            value = parameter.get('VALUE')
            if key in parameters and parameters[key] != value:
                raise ValueError('Conflicting IP parameter ' + name + '/' + key)
            parameters[key] = value
        ips[name] = {'vlnv': module.get('VLNV'), 'modtype': module.get('MODTYPE'), 'parameters': parameters}
    return {'device': device, 'vivado': root.get('VIVADOVERSION'), 'ips': ips}, {
        'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path),
        'hwh_member': selected, 'hwh_sha256': hashlib.sha256(raw).hexdigest()}

def normalize_device(value):
    if not isinstance(value, str):
        raise ValueError('Device must be a nonempty string')
    value = value.lower().removeprefix('xc')
    match = re.match(r'^(7z[0-9]{3}|zu[0-9]+[a-z]*)', value)
    if not match:
        raise ValueError('Unsupported device identity: ' + value)
    return match.group(1)

def bit_part(path):
    # Xilinx .bit header fields a-d use 16-bit lengths; e begins payload.
    with Path(path).open('rb') as stream:
        raw = stream.read(65536)
    def u16(pos):
        if pos + 2 > len(raw):
            raise ValueError('Truncated BIT header')
        return int.from_bytes(raw[pos:pos + 2], 'big')
    pos = 2 + u16(0)
    if u16(pos) != 1:
        raise ValueError('Unsupported BIT header')
    pos += 2
    for _ in range(4):
        if pos >= len(raw) or raw[pos:pos + 1] not in (b'a', b'b', b'c', b'd'):
            raise ValueError('Unsupported BIT header field')
        key = raw[pos:pos + 1]
        size = u16(pos + 1)
        pos += 3
        if pos + size > len(raw):
            raise ValueError('Truncated BIT header field')
        value = raw[pos:pos + size].rstrip(b'\x00').decode('ascii')
        pos += size
        if key == b'b':
            return value
    raise ValueError('BIT device field missing')

def decode_dmasr(value):
    value = integer(value, 'DMASR')
    if value > 0xffffffff:
        raise ValueError('DMASR exceeds 32 bits')
    masks = {'halted': 1, 'idle': 2, 'sg_included': 8, 'dma_internal_error': 16, 'dma_slave_error': 32, 'dma_decode_error': 64, 'sg_internal_error': 256, 'sg_slave_error': 512, 'sg_decode_error': 1024, 'ioc_irq': 4096, 'delay_irq': 8192, 'error_irq': 16384}
    return {'hex': hex(value), 'bits': {name: bool(value & mask) for name, mask in masks.items()}, 'interpretation': 'Snapshot only; not a unique root cause or authorization to reset.'}

def audit(metadata, identity, config, bit=None):
    findings = []
    transfers = []
    def add(severity, code, message):
        findings.append({'severity': severity, 'code': code, 'message': message})
    device = metadata['device']
    if not device:
        add('unknown', 'DEVICE_MISSING', 'HWH does not identify a device.')
    elif config.get('expected_device'):
        if normalize_device(device) != normalize_device(config['expected_device']):
            add('error', 'DEVICE_MISMATCH', 'Expected ' + config['expected_device'] + ', HWH declares ' + device)
    else:
        add('unknown', 'EXPECTED_DEVICE_MISSING', 'Provide expected_device to check the intended device.')
    bit_identity = None
    if bit:
        part = bit_part(bit)
        bit_identity = {'file': Path(bit).name, 'sha256': sha(bit), 'part': part}
        if device and normalize_device(part) != normalize_device(device):
            add('error', 'BIT_DEVICE_MISMATCH', 'BIT and HWH identify different devices.')
        add('info', 'PAIRING_NOT_PROVEN', 'Matching device and hashes do not prove BIT/HWH came from the same build; bind them to a build manifest.')
    else:
        add('unknown', 'BIT_NOT_CHECKED', 'No BIT supplied; pairing and hardware identity are not checked.')
    required = config.get('required_ips', [])
    if not isinstance(required, list):
        raise ValueError('required_ips must be a list')
    for item in required:
        if not isinstance(item, dict) or set(item) - {'name', 'vlnv_contains'} or not isinstance(item.get('name'), str):
            raise ValueError('Invalid required_ips entry')
        name = item['name'].strip('/')
        ip = metadata['ips'].get(name)
        if ip is None:
            add('error', 'IP_MISSING', 'Missing exact hierarchical IP path: ' + name)
        elif item.get('vlnv_contains') and item['vlnv_contains'] not in (ip['vlnv'] or ''):
            add('error', 'IP_TYPE_MISMATCH', 'Unexpected VLNV for ' + name)
    dma = config.get('dma')
    if dma is not None:
        if not isinstance(dma, dict) or set(dma) - {'ip', 'transfers'} or not isinstance(dma.get('ip'), str):
            raise ValueError('dma requires exact ip path and transfers')
        name = dma['ip'].strip('/')
        ip = metadata['ips'].get(name)
        if ip is None:
            add('error', 'DMA_MISSING', 'No DMA at ' + name + '; do not map a native accelerator to AXI DMA by name.')
        elif ':axi_dma:' not in (ip['vlnv'] or ''):
            add('error', 'DMA_TYPE_MISMATCH', name + ' is not Xilinx AXI DMA.')
        else:
            params = ip['parameters']
            def param(key):
                value = params.get(key)
                if value is None:
                    add('unknown', 'PARAMETER_MISSING', name + '/' + key + ' unavailable; no guessed default.')
                    return None
                return integer(value, key)
            sg = param('c_include_sg')
            if sg not in (0, None):
                add('unknown', 'SG_NOT_EVALUATED', 'This tool evaluates simple AXI DMA only; SG/micro DMA needs its own contract.')
            micro = param('c_micro_dma')
            if micro not in (0, None):
                add('unknown', 'MICRO_DMA_NOT_EVALUATED', 'Micro DMA limits differ; simple-DMA byte bound is not applicable.')
            width = param('c_sg_length_width')
            if width is not None and not 8 <= width <= 26:
                raise ValueError('Invalid AXI DMA C_SG_LENGTH_WIDTH')
            specs = dma.get('transfers')
            if not isinstance(specs, list) or not specs:
                raise ValueError('dma.transfers must be a nonempty list')
            for spec in specs:
                if not isinstance(spec, dict) or set(spec) - {'direction', 'shape', 'dtype', 'buffer_bytes', 'start_bytes', 'physical_address'}:
                    raise ValueError('Invalid DMA transfer fields')
                direction = spec.get('direction')
                if direction not in ('mm2s', 's2mm'):
                    raise ValueError('direction must be mm2s or s2mm')
                shape = spec.get('shape')
                if not isinstance(shape, list) or not shape or len(shape) > 8:
                    raise ValueError('shape must contain 1..8 positive dimensions')
                elements = math.prod(integer(v, 'shape dimension', 1) for v in shape)
                dtype = spec.get('dtype')
                if dtype not in DTYPE_BYTES:
                    raise ValueError('Unsupported dtype; explicit byte width required')
                nbytes = elements * DTYPE_BYTES[dtype]
                capacity = integer(spec.get('buffer_bytes'), 'buffer_bytes', 1)
                start = integer(spec.get('start_bytes', 0), 'start_bytes')
                enabled = param('c_include_' + direction)
                if enabled == 0:
                    add('error', 'CHANNEL_DISABLED', direction + ' is not enabled.')
                maximum = (1 << width) - 1 if width is not None and sg == 0 and micro == 0 else None
                if maximum is not None and nbytes > maximum:
                    add('error', 'LENGTH_EXCEEDS_DMA', direction + ': ' + str(nbytes) + ' bytes exceeds ' + str(maximum) + '; redesign/tile with matching stream boundaries, not blind slicing.')
                if start + nbytes > capacity:
                    add('error', 'BUFFER_TOO_SMALL', direction + ': start + transfer exceeds allocated buffer.')
                dre = param('c_include_' + direction + '_dre')
                bus_width = param('c_m_axi_' + direction + '_data_width')
                if bus_width is not None and (bus_width < 8 or bus_width % 8):
                    raise ValueError('DMA memory-map data width must be positive whole bytes')
                address = spec.get('physical_address')
                if address is None:
                    add('unknown', 'ADDRESS_NOT_OBSERVED', direction + ': collect allocated physical_address and start; offline buffer size cannot prove alignment.')
                elif dre == 0 and bus_width is not None and (integer(address, 'physical_address') + start) % (bus_width // 8):
                    add('error', 'ADDRESS_UNALIGNED', direction + ': physical address + start violates non-DRE alignment.')
                transfers.append({'direction': direction, 'shape': shape, 'dtype': dtype, 'bytes': nbytes, 'buffer_bytes': capacity, 'start_bytes': start, 'max_simple_dma_bytes': maximum})
    else:
        add('info', 'DMA_NOT_REQUESTED', 'Only overlay/IP inventory requested; no DMA transfer check.')
    add('info', 'STATIC_LIMIT', 'No hardware or notebook executed. TLAST, TKEEP, coherent ownership, content correctness and timing are not observed.')
    state = 'BLOCKED' if any(f['severity'] == 'error' for f in findings) else 'INCOMPLETE' if any(f['severity'] == 'unknown' for f in findings) else 'STATIC_CHECKS_PASSED'
    return {'schema': 'pynq-overlay-audit-report-v1', 'status': state, 'hardware_execution': False, 'metadata': identity, 'bit': bit_identity, 'device': device, 'ip_inventory': metadata['ips'], 'transfers': transfers, 'findings': findings}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hwh', required=True, type=Path, help='HWH or XSA containing HWH; no extraction side effects')
    parser.add_argument('--member', help='Exact HWH archive member when ambiguous')
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--bit', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--dmasr', help='Optional observed DMASR integer/hex; decoded offline')
    args = parser.parse_args(argv)
    for source in [args.hwh, args.config, args.bit]:
        if source is not None and source.resolve() == args.out.resolve():
            parser.error('--out must not overwrite an input')
    try:
        config = load_config(args.config)
        metadata, identity = read_metadata(args.hwh, args.member)
        report = audit(metadata, identity, config, args.bit)
        report['contract_sha256'] = sha(args.config)
        if args.dmasr is not None:
            report['dmasr'] = decode_dmasr(args.dmasr)
        code = 2 if report['status'] == 'BLOCKED' else 4 if report['status'] == 'INCOMPLETE' else 0
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile, KeyError, TypeError) as error:
        report = {'schema': 'pynq-overlay-audit-report-v1', 'status': 'INVALID_INPUT', 'hardware_execution': False, 'error': str(error)}
        code = 3
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'report': str(args.out), 'hardware_execution': False}, ensure_ascii=False))
    return code

if __name__ == '__main__':
    sys.exit(main())
