"""Focused regressions for nine-class deployment metadata and 18-class V8PK compatibility."""
import json
import hashlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

DEPLOYMENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOYMENT))
from export_graph import ordered_class_names, validate_domain_class_names
from pack_model import pack
from quantize import (load_dataset_manifest, materialize_manifest_record,
                      select_calibration_records)


CLASS_NAMES = [f'PCB_{index}' for index in range(9)] + [f'PIN_{index}' for index in range(9)]
PIN_NAMES = CLASS_NAMES[9:]


def graph_for(domain):
    classes = PIN_NAMES if domain == 'pin' else CLASS_NAMES if domain == 'joint18' else CLASS_NAMES[:9]
    count = len(classes)
    return {
        'format': 'V8GRAPH', 'version': 1, 'domain': domain, 'class_count': count,
        'classes': classes, 'source_class_ids': list(range(9, 18)) if domain == 'pin' else list(range(count)),
        'reg_max': 16, 'input_shape': [1, 3, 416, 416], 'input_size': 416,
        'checkpoint_sha256': 'a' * 64,
    }


def official_manifest(path, rows):
    path.write_text(json.dumps({'version': 1, 'class_names': CLASS_NAMES, 'records': rows}), encoding='utf-8')
    return path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(record_id, domain, split, image, class_id):
    return {'id': record_id, 'domain': domain, 'split': split, 'image': str(image),
            'boxes': [{'class_id': class_id, 'xyxy': [.1, .2, .5, .7]}]}


class ModelMigrationTests(unittest.TestCase):
    def test_ordered_class_names_rejects_duplicate_or_blank_names(self):
        self.assertEqual(ordered_class_names({i: name for i, name in enumerate(PIN_NAMES)}, 9), PIN_NAMES)
        with self.assertRaisesRegex(ValueError, 'unique'):
            ordered_class_names({i: 'same' for i in range(9)}, 9)
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            ordered_class_names({i: (' ' if i == 0 else str(i)) for i in range(9)}, 9)

    def test_domain_mismatch_is_rejected_from_class_name_prefixes(self):
        validate_domain_class_names(PIN_NAMES, 'pin')
        with self.assertRaisesRegex(ValueError, 'PCB checkpoints'):
            validate_domain_class_names(PIN_NAMES, 'pcb')
        with self.assertRaisesRegex(ValueError, 'joint18 checkpoints'):
            validate_domain_class_names(PIN_NAMES + CLASS_NAMES[:9], 'joint18')

    def test_official_records_calibration_is_domain_and_train_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            train_image = root / 'pin_train.jpg'
            val_image = root / 'pin_val.jpg'
            pcb_image = root / 'pcb_train.jpg'
            for path in (train_image, val_image, pcb_image):
                path.write_bytes(b'image fixture')
            manifest = official_manifest(root / 'records.json', [
                record('pin_train_0', 'pin', 'train', train_image, 9),
                record('pin_val_0', 'pin', 'val', val_image, 9),
                record('pcb_train_0', 'pcb', 'train', pcb_image, 0),
            ])
            selected, metadata = select_calibration_records(manifest, 'pin', 2, graph_for('pin'))
            self.assertEqual([row['id'] for row in selected], ['pin_train_0'])
            self.assertEqual(selected[0]['source_class_ids'], [9])
            self.assertEqual(metadata['source_class_ids'], list(range(9, 18)))
            with self.assertRaisesRegex(ValueError, 'does not match graph domain'):
                select_calibration_records(manifest, 'pcb', 2, graph_for('pin'))

    def test_joint18_selects_both_train_domains_and_never_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = []
            for domain, global_id in (('pcb', 0), ('pin', 9)):
                for split in ('train', 'val'):
                    image = root / f'{domain}_{split}.jpg'
                    image.write_bytes(b'image fixture')
                    rows.append(record(f'{domain}_{split}_0', domain, split, image, global_id))
            manifest = official_manifest(root / 'records.json', rows)
            selected, metadata = select_calibration_records(manifest, 'joint18', 1, graph_for('joint18'))
            self.assertEqual({row['domain'] for row in selected}, {'pcb', 'pin'})
            self.assertTrue(all(row['split'] == 'train' for row in selected))
            self.assertEqual(metadata['class_count'], 18)

    def test_data_manifest_uses_absolute_paths_and_source_global_class_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / 'pin-image.jpg'
            label = root / 'pin-source.txt'
            image.write_bytes(b'image fixture')
            label.write_text('9 0.5 0.5 0.25 0.25\n', encoding='utf-8')
            manifest = root / 'data_manifest.json'
            manifest.write_text(json.dumps([{
                'domain': 'pin', 'split': 'train', 'image': str(image),
                'source_image': str(image), 'source_label': str(label),
            }]), encoding='utf-8')
            records, names = load_dataset_manifest(manifest)
            self.assertIsNone(names)
            self.assertEqual(records[0]['image_path'], image.resolve())
            self.assertEqual(materialize_manifest_record(records[0])['source_class_ids'], [9])
            selected, _ = select_calibration_records(manifest, 'pin', 1, graph_for('pin'))
            self.assertEqual(selected[0]['source_class_ids'], [9])

    def test_data_manifest_rejects_off_domain_source_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / 'pin-image.jpg'
            label = root / 'wrong-source.txt'
            image.write_bytes(b'image fixture')
            label.write_text('0 0.5 0.5 0.25 0.25\n', encoding='utf-8')
            manifest = root / 'data_manifest.json'
            manifest.write_text(json.dumps([{
                'domain': 'pin', 'split': 'train', 'image': str(image),
                'source_label': str(label),
            }]), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Off-domain class ID'):
                select_calibration_records(manifest, 'pin', 1, graph_for('pin'))

    def _write_single_domain_data_manifest(self, root, *, source_box='9 0.5 0.5 0.25 0.25',
                                           local_box='0 0.5 0.5 0.25 0.25'):
        image = root / 'images' / 'train' / 'pin-image.jpg'
        image.parent.mkdir(parents=True)
        image.write_bytes(b'image fixture')
        source_label = root / 'source-labels' / 'pin-source.txt'
        source_label.parent.mkdir()
        source_label.write_text(source_box + '\n', encoding='utf-8')
        local_label = root / 'labels' / 'train' / 'pin-image.txt'
        local_label.parent.mkdir(parents=True)
        local_label.write_text(local_box + '\n', encoding='utf-8')
        manifest = root / 'data_manifest.json'
        manifest.write_text(json.dumps([{
            'id': 'pin-train', 'domain': 'pin', 'split': 'train',
            'image': str(image), 'source_label': str(source_label),
            'image_sha256': sha256(image),
            'source_label_sha256': sha256(source_label),
            'label_sha256': sha256(local_label),
        }]), encoding='utf-8')
        return manifest, image, source_label, local_label

    def test_data_manifest_rejects_selected_image_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest, image, _source_label, _local_label = self._write_single_domain_data_manifest(Path(temp))
            image.write_bytes(b'tampered image')
            with self.assertRaisesRegex(ValueError, 'Selected image SHA-256 mismatch'):
                select_calibration_records(manifest, 'pin', 1, graph_for('pin'))

    def test_data_manifest_rejects_source_label_hash_mismatch_before_parsing(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest, _image, source_label, _local_label = self._write_single_domain_data_manifest(Path(temp))
            source_label.write_text('malformed source label\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Source label SHA-256 mismatch'):
                select_calibration_records(manifest, 'pin', 1, graph_for('pin'))

    def test_data_manifest_rejects_local_label_mapping_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest, _image, _source_label, _local_label = self._write_single_domain_data_manifest(
                Path(temp), local_box='0 0.6 0.5 0.25 0.25')
            rows, _names = load_dataset_manifest(manifest, splits={'train'})
            with self.assertRaisesRegex(ValueError, 'Source/global and local labels disagree'):
                materialize_manifest_record(rows[0])

    def _pack_fixture(self, root, domain):
        model_dir = root / f'model_{domain}'
        quant_dir = root / f'quant_{domain}'
        model_dir.mkdir()
        quant_dir.mkdir()
        graph = graph_for(domain)
        graph.update(nodes=[{'id': 0, 'op': 'silu', 'inputs': [-1], 'shape': [1, 1, 1, 1]}],
                     outputs=[0], strides=[416], checkpoint_sha256='a' * 64)
        (model_dir / 'graph.json').write_text(json.dumps(graph), encoding='utf-8')
        np.savez(quant_dir / 'weights_int8.npz', lut_0=np.zeros(256, dtype=np.int8))
        domains = ['pcb', 'pin'] if domain == 'joint18' else [domain]
        rows = []
        calibration_ids = []
        covered_ids = []
        for task in domains:
            global_id = 0 if task == 'pcb' else 9
            image = root / f'{domain}_{task}_train.jpg'
            image.write_bytes(b'calibration image fixture')
            record_id = f'{domain}-{task}-train'
            rows.append(record(record_id, task, 'train', image, global_id))
            calibration_ids.append(record_id)
            covered_ids.append(global_id)
        manifest = official_manifest(root / f'{domain}_calibration.json', rows)
        source_to_local = {source_id: local_id for local_id, source_id in
                           enumerate(graph['source_class_ids'])}
        spec = {
            'model_sha256': graph['checkpoint_sha256'], 'domain': domain,
            'class_count': graph['class_count'], 'classes': graph['classes'],
            'source_class_ids': graph['source_class_ids'], 'reg_max': 16,
            'input_shape': [1, 3, 416, 416], 'input_size': 416,
            'calibration_split': 'train', 'calibration_ids': calibration_ids,
            'calibration_manifest': str(manifest.resolve()),
            'calibration_manifest_sha256': sha256(manifest),
            'calibration_domains': domains,
            'source_global_class_ids_covered': sorted(covered_ids),
            'classes_covered': sorted(source_to_local[source_id] for source_id in covered_ids),
            'scales': {'-1': 0.01, '0': 0.02},
        }
        (quant_dir / 'quantization.json').write_text(json.dumps(spec), encoding='utf-8')
        return model_dir, quant_dir

    def test_package_header_macros_and_graph_metadata_agree_for_nine_classes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_dir, quant_dir = self._pack_fixture(root, 'pin')
            out = root / 'package'
            pack(model_dir, quant_dir, out)
            package = (out / 'MODEL.V8P').read_bytes()
            magic, version, _payload, _crc, _nodes, _arena, class_count, input_size = struct.unpack(
                '<4s7I', package[:32])
            self.assertEqual((magic, version, class_count, input_size), (b'V8PK', 1, 9, 416))
            header = (out / 'v8_generated_model.h').read_text(encoding='utf-8')
            for expected in ('#define V8_CLASS_DOMAIN "pin"', '#define V8_CLASS_COUNT 9u',
                             '#define V8_REG_MAX 16u', '#define V8_INPUT_SIZE 416u',
                             '#define V8_CLASSES_SHA256 "', '.classes=9u,.reg_max=16u,.input_size=416u'):
                self.assertIn(expected, header)
            metadata = json.loads((out / 'package.json').read_text(encoding='utf-8'))
            self.assertEqual((metadata['domain'], metadata['class_count'], metadata['reg_max']),
                             ('pin', 9, 16))

    def test_historical_eighteen_class_package_header_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_dir, quant_dir = self._pack_fixture(root, 'joint18')
            graph_path = model_dir / 'graph.json'
            graph = json.loads(graph_path.read_text(encoding='utf-8'))
            for key in ('domain', 'class_count', 'input_size', 'source_class_ids'):
                graph.pop(key)
            graph_path.write_text(json.dumps(graph), encoding='utf-8')
            spec_path = quant_dir / 'quantization.json'
            spec = json.loads(spec_path.read_text(encoding='utf-8'))
            for key in ('domain', 'class_count', 'classes', 'source_class_ids', 'reg_max',
                        'input_shape', 'input_size', 'calibration_manifest',
                        'calibration_manifest_sha256',
                        'calibration_domains'):
                spec.pop(key)
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            out = root / 'package18'
            pack(model_dir, quant_dir, out)
            package = (out / 'MODEL.V8P').read_bytes()
            header_fields = struct.unpack('<4s7I', package[:32])
            self.assertEqual(header_fields[0:2], (b'V8PK', 1))
            self.assertEqual(header_fields[6:], (18, 416))
            generated = (out / 'v8_generated_model.h').read_text(encoding='utf-8')
            self.assertIn('#define V8_CLASS_DOMAIN "joint18"', generated)
            self.assertIn('#define V8_CLASS_COUNT 18u', generated)

    def test_pack_rejects_quantization_metadata_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_dir, quant_dir = self._pack_fixture(root, 'pcb')
            spec_path = quant_dir / 'quantization.json'
            spec = json.loads(spec_path.read_text(encoding='utf-8'))
            spec['class_count'] = 18
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'class count/model mismatch'):
                pack(model_dir, quant_dir, root / 'bad-package')

    def test_nine_class_pack_rejects_missing_quantization_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_dir, quant_dir = self._pack_fixture(root, 'pcb')
            spec_path = quant_dir / 'quantization.json'
            spec = json.loads(spec_path.read_text(encoding='utf-8'))
            spec.pop('input_size')
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'missing required fields:.*input_size'):
                pack(model_dir, quant_dir, root / 'bad-package')

    def test_pack_accepts_relocated_manifest_override_with_matching_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_dir, quant_dir = self._pack_fixture(root, 'pin')
            spec_path = quant_dir / 'quantization.json'
            spec = json.loads(spec_path.read_text(encoding='utf-8'))
            manifest = Path(spec['calibration_manifest'])
            spec['calibration_manifest'] = str(root / 'old-location' / manifest.name)
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            pack(model_dir, quant_dir, root / 'relocated-package', manifest_override=manifest)
            self.assertTrue((root / 'relocated-package' / 'MODEL.V8P').is_file())


if __name__ == '__main__':
    unittest.main()
