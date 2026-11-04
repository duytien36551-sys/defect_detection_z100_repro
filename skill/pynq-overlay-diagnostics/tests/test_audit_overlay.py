"""Behavioral regressions for audit_overlay.py using synthetic HWH/BIT fixtures only."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'audit_overlay.py'
sys.path.insert(0, str(SCRIPT.parent))
import audit_overlay

DMA_MAX = (1 << 14) - 1


def base_parameters():
    return {
        'c_include_sg': '0',
        'c_micro_dma': '0',
        'c_sg_length_width': '14',
        'c_include_mm2s': '1',
        'c_include_s2mm': '1',
        'c_include_mm2s_dre': '0',
        'c_include_s2mm_dre': '0',
        'c_m_axi_mm2s_data_width': '64',
        'c_m_axi_s2mm_data_width': '64',
    }


def make_transfer(shape=None, dtype='uint8', buffer_bytes=65536,
                  start_bytes=0, physical_address=0x1000, direction='mm2s'):
    return {
        'direction': direction,
        'shape': [1] if shape is None else shape,
        'dtype': dtype,
        'buffer_bytes': buffer_bytes,
        'start_bytes': start_bytes,
        'physical_address': physical_address,
    }


def run_audit(transfer=None, params=None, ip_path='axi_dma_0', device='7z020',
              expected_device='xc7z020clg400-1', vlnv='xilinx.com:ip:axi_dma:7.1',
              transfers=None, bit=None, required_ips=None, dma_ip=None):
    if transfers is None:
        transfers = [make_transfer() if transfer is None else transfer]
    values = base_parameters() if params is None else dict(params)
    metadata = {
        'device': device,
        'vivado': 'synthetic-fixture',
        'ips': {ip_path: {'vlnv': vlnv, 'modtype': 'axi_dma', 'parameters': values}},
    }
    config = {
        'schema': 'pynq-overlay-contract-v1',
        'expected_device': expected_device,
        'required_ips': [] if required_ips is None else required_ips,
        'dma': {'ip': (ip_path if dma_ip is None else dma_ip), 'transfers': transfers},
    }
    identity = {'file': 'synthetic.hwh', 'bytes': 1, 'sha256': 'synthetic-fixture'}
    return audit_overlay.audit(metadata, identity, config, bit)


def codes(report):
    return {item['code'] for item in report['findings']}


def synthetic_bit(path, part):
    def field(tag, value):
        payload = value.encode('ascii')
        return tag + len(payload).to_bytes(2, 'big') + payload
    raw = (b'\x00\x01\x00\x00\x01' + field(b'a', 'synthetic')
           + field(b'b', part) + field(b'c', '2026/11/03')
           + field(b'd', '00:00:00'))
    path.write_bytes(raw)
    return path


class SyntheticDmaSafetyTests(unittest.TestCase):
    def test_simple_dma_accepts_exact_length_field_maximum(self):
        report = run_audit(make_transfer([DMA_MAX], buffer_bytes=DMA_MAX))
        self.assertNotIn('LENGTH_EXCEEDS_DMA', codes(report))
        self.assertEqual(report['transfers'][0]['max_simple_dma_bytes'], DMA_MAX)

    def test_simple_dma_rejects_one_byte_above_length_field_maximum(self):
        report = run_audit(make_transfer([DMA_MAX + 1], buffer_bytes=DMA_MAX + 1))
        self.assertIn('LENGTH_EXCEEDS_DMA', codes(report))

    def test_dtype_controls_transfer_byte_count(self):
        report = run_audit(transfers=[
            make_transfer([2, 4], dtype='uint8', buffer_bytes=32),
            make_transfer([2, 4], dtype='float32', buffer_bytes=32),
        ])
        self.assertEqual([item['bytes'] for item in report['transfers']], [8, 32])

    def test_capacity_check_includes_start_offset_and_length(self):
        short = run_audit(make_transfer([8], start_bytes=8, buffer_bytes=15))
        exact = run_audit(make_transfer([8], start_bytes=8, buffer_bytes=16))
        self.assertIn('BUFFER_TOO_SMALL', codes(short))
        self.assertNotIn('BUFFER_TOO_SMALL', codes(exact))

    def test_non_dre_alignment_checks_physical_address_plus_start(self):
        misaligned = run_audit(make_transfer([8], start_bytes=3, physical_address=0x1000))
        aligned_sum = run_audit(make_transfer([8], start_bytes=3, physical_address=0x1005))
        self.assertIn('ADDRESS_UNALIGNED', codes(misaligned))
        self.assertNotIn('ADDRESS_UNALIGNED', codes(aligned_sum))

    def test_hierarchical_dma_paths_are_matched_exactly(self):
        path = 'system_i/processing_system7_0/axi_dma_0'
        correct = run_audit(ip_path=path, required_ips=[{'name': path, 'vlnv_contains': 'axi_dma'}])
        wrong = run_audit(ip_path=path, dma_ip='axi_dma_0', required_ips=[{'name': path}])
        self.assertNotIn('IP_MISSING', codes(correct))
        self.assertIn('DMA_MISSING', codes(wrong))
        self.assertNotIn('IP_MISSING', codes(wrong))

    def test_missing_length_or_sg_mode_parameters_stay_unknown(self):
        for key in ('c_sg_length_width', 'c_include_sg'):
            with self.subTest(parameter=key):
                params = base_parameters()
                params.pop(key)
                report = run_audit(make_transfer([100], buffer_bytes=1000), params=params)
                self.assertIn('PARAMETER_MISSING', codes(report))
                self.assertIsNone(report['transfers'][0]['max_simple_dma_bytes'])

    def test_missing_micro_dma_mode_stays_unknown(self):
        params = base_parameters()
        params.pop('c_micro_dma')
        report = run_audit(make_transfer([8], buffer_bytes=8), params=params)
        self.assertIn('PARAMETER_MISSING', codes(report))
        self.assertIsNone(report['transfers'][0]['max_simple_dma_bytes'])

    def test_missing_micro_dma_mode_does_not_apply_simple_dma_bound(self):
        params = base_parameters()
        params.pop('c_micro_dma')
        report = run_audit(make_transfer([DMA_MAX + 1], buffer_bytes=DMA_MAX + 1), params=params)
        self.assertNotIn('LENGTH_EXCEEDS_DMA', codes(report))
        self.assertIsNone(report['transfers'][0]['max_simple_dma_bytes'])

    def test_disabled_direction_is_reported_as_error(self):
        params = base_parameters()
        params['c_include_mm2s'] = '0'
        report = run_audit(make_transfer([8], buffer_bytes=8), params=params)
        self.assertIn('CHANNEL_DISABLED', codes(report))

    def test_scatter_gather_does_not_receive_simple_mode_bound(self):
        params = base_parameters()
        params['c_include_sg'] = '1'
        report = run_audit(make_transfer([DMA_MAX + 1], buffer_bytes=DMA_MAX + 1), params=params)
        self.assertIn('SG_NOT_EVALUATED', codes(report))
        self.assertNotIn('LENGTH_EXCEEDS_DMA', codes(report))
        self.assertIsNone(report['transfers'][0]['max_simple_dma_bytes'])

    def test_micro_dma_does_not_receive_simple_mode_bound(self):
        params = base_parameters()
        params['c_micro_dma'] = '1'
        report = run_audit(make_transfer([DMA_MAX + 1], buffer_bytes=DMA_MAX + 1), params=params)
        self.assertIn('MICRO_DMA_NOT_EVALUATED', codes(report))
        self.assertNotIn('LENGTH_EXCEEDS_DMA', codes(report))
        self.assertIsNone(report['transfers'][0]['max_simple_dma_bytes'])


class SyntheticMetadataTests(unittest.TestCase):
    def test_bit_hwh_device_mismatch_is_reported(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            bit = synthetic_bit(Path(tmp) / 'wrong_device.bit', 'xc7z010clg400-1')
            report = run_audit(make_transfer([8], buffer_bytes=8), bit=bit)
            self.assertIn('BIT_DEVICE_MISMATCH', codes(report))
            self.assertEqual(report['bit']['part'], 'xc7z010clg400-1')

    def test_hwh_reader_preserves_hierarchical_module_and_parameters(self):
        xml = (b'<HWH VIVADOVERSION="2024.1"><SYSTEMINFO ARCH="zynq" DEVICE="7z020"/>'
               b'<MODULE FULLNAME="top/system_i/axi_dma_0" VLNV="xilinx.com:ip:axi_dma:7.1" MODTYPE="axi_dma">'
               b'<PARAMETERS><PARAMETER NAME="C_INCLUDE_SG" VALUE="0"/></PARAMETERS>'
               b'</MODULE></HWH>')
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = Path(tmp) / 'synthetic.hwh'
            path.write_bytes(xml)
            metadata, identity = audit_overlay.read_metadata(path)
        self.assertEqual(metadata['device'], '7z020')
        self.assertIn('top/system_i/axi_dma_0', metadata['ips'])
        self.assertEqual(metadata['ips']['top/system_i/axi_dma_0']['parameters']['c_include_sg'], '0')
        self.assertEqual(identity['hwh_sha256'], audit_overlay.hashlib.sha256(xml).hexdigest())

    def test_malformed_xml_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = Path(tmp) / 'malformed.hwh'
            path.write_bytes(b'<HWH><SYSTEMINFO DEVICE="7z020"></HWH>')
            with self.assertRaises(audit_overlay.ET.ParseError):
                audit_overlay.read_metadata(path)

    def test_entity_declaration_metadata_is_rejected(self):
        xml = b'<!DOCTYPE HWH [<!ENTITY x "y">]><HWH><SYSTEMINFO DEVICE="7z020"/></HWH>'
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = Path(tmp) / 'entity.hwh'
            path.write_bytes(xml)
            with self.assertRaisesRegex(ValueError, 'DTD/entity'):
                audit_overlay.read_metadata(path)

    def test_duplicate_json_fields_are_rejected_at_any_level(self):
        duplicate_documents = [
            '{"schema":"pynq-overlay-contract-v1","schema":"pynq-overlay-contract-v1"}',
            '{"schema":"pynq-overlay-contract-v1","dma":{"ip":"a","ip":"b"}}',
        ]
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            for index, document in enumerate(duplicate_documents):
                with self.subTest(level=index):
                    path = Path(tmp) / f'duplicate_{index}.json'
                    path.write_text(document, encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'Duplicate JSON field'):
                        audit_overlay.load_config(path)


if __name__ == '__main__':
    unittest.main()



