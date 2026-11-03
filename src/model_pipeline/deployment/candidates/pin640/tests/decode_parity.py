"""Portable C/Python parity checks for the raw YOLOv8 head contract."""

from __future__ import annotations

import ctypes
import pathlib
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reference"))
from v8_decode import Detection, Letterbox, decode_raw_heads, filter_classes, project_box  # noqa: E402


class CHead(ctypes.Structure):
    _fields_ = [("data", ctypes.POINTER(ctypes.c_float)), ("width", ctypes.c_int),
                ("height", ctypes.c_int), ("stride", ctypes.c_int)]


class CConfig(ctypes.Structure):
    _fields_ = [("input_width", ctypes.c_int), ("input_height", ctypes.c_int),
                ("classes", ctypes.c_int), ("reg_max", ctypes.c_int),
                ("confidence", ctypes.c_float), ("iou", ctypes.c_float),
                ("multi_label", ctypes.c_int),
                ("class_confidence", ctypes.POINTER(ctypes.c_float)),
                ("class_confidence_count", ctypes.c_size_t)]


class CDetection(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("x1", "y1", "x2", "y2", "score")] + [
        ("class_id", ctypes.c_int)
    ]


class CLetterbox(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in (
        "original_width", "original_height", "input_width", "input_height"
    )] + [(name, ctypes.c_float) for name in (
        "scale_x", "scale_y", "pad_left", "pad_top"
    )]


def synthetic_head(width: int = 2, height: int = 2, classes: int = 18,
                   reg_max: int = 4) -> np.ndarray:
    raw = np.full((1, 4 * reg_max + classes, height, width), -20.0, dtype=np.float32)
    for side in range(4):
        raw[0, side * reg_max + 1] = 20.0
    return raw


class DecodeParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.library_path = pathlib.Path(cls.temp.name) / "v8_decode.dll"
        subprocess.run([
            "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-shared",
            str(ROOT / "firmware" / "v8_decode.c"), "-lm", "-o", str(cls.library_path),
        ], check=True, capture_output=True, text=True)
        cls.library = ctypes.CDLL(str(cls.library_path))
        cls.library.v8_decode_raw.argtypes = [ctypes.POINTER(CHead), ctypes.c_size_t,
                                               ctypes.POINTER(CConfig),
                                               ctypes.POINTER(CDetection), ctypes.c_size_t,
                                               ctypes.POINTER(ctypes.c_size_t)]
        cls.library.v8_decode_raw.restype = ctypes.c_int
        cls.library.v8_project_box.argtypes = [ctypes.POINTER(CDetection),
                                                ctypes.POINTER(CLetterbox),
                                                ctypes.POINTER(CDetection)]
        cls.library.v8_project_box.restype = ctypes.c_int
        cls.library.v8_filter_classes.argtypes = [ctypes.POINTER(CDetection), ctypes.c_size_t,
                                                   ctypes.c_int, ctypes.c_int,
                                                   ctypes.POINTER(CDetection)]
        cls.library.v8_filter_classes.restype = ctypes.c_size_t

    @classmethod
    def tearDownClass(cls) -> None:
        if sys.platform == "win32":
            handle = cls.library._handle
            del cls.library
            ctypes.windll.kernel32.FreeLibrary(ctypes.c_void_p(handle))
        cls.temp.cleanup()

    def c_decode(self, arrays: list[np.ndarray], strides: list[int],
                 *, confidence: float = 0.5, iou: float = 0.7,
                 cap: int = 300, multi_label: bool = True,
                 input_size: int = 32, classes: int = 18) -> list[CDetection]:
        arrays = [np.ascontiguousarray(array, dtype=np.float32) for array in arrays]
        heads = (CHead * len(arrays))(*[
            CHead(array.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), array.shape[3],
                  array.shape[2], stride) for array, stride in zip(arrays, strides)
        ])
        reg_max = (arrays[0].shape[1] - classes) // 4
        config = CConfig(input_size, input_size, classes, reg_max,
                         confidence, iou, int(multi_label), None, 0)
        output = (CDetection * cap)()
        count = ctypes.c_size_t()
        status = self.library.v8_decode_raw(heads, len(arrays), ctypes.byref(config),
                                            output, cap, ctypes.byref(count))
        self.assertEqual(status, 0)
        return list(output)[:count.value]

    def compare(self, arrays: list[np.ndarray], strides: list[int],
                *, confidence: float = 0.5, iou: float = 0.7,
                cap: int = 300, multi_label: bool = True,
                input_size: int = 32, classes: int = 18) -> list[CDetection]:
        python = decode_raw_heads(arrays, strides=strides, input_width=input_size,
                                  input_height=input_size, classes=classes,
                                  reg_max=(arrays[0].shape[1] - classes) // 4,
                                  confidence=confidence, iou=iou,
                                  max_detections=cap, multi_label=multi_label)
        c = self.c_decode(arrays, strides, confidence=confidence, iou=iou, cap=cap,
                          multi_label=multi_label, input_size=input_size, classes=classes)
        self.assertEqual(len(python), len(c))
        for expected, actual in zip(python, c):
            self.assertEqual(expected.class_id, actual.class_id)
            for name in ("x1", "y1", "x2", "y2", "score"):
                self.assertAlmostEqual(getattr(expected, name), getattr(actual, name), places=5)
        return c

    def test_dfl_multilabel_and_global_cap(self) -> None:
        raw = synthetic_head()
        raw[0, 16 + 17, 0, 0] = 12.0
        raw[0, 16 + 0, 0, 1] = 2.0
        raw[0, 16 + 8, 0, 0] = 3.0
        found = self.compare([raw], [16], cap=2)
        self.assertEqual([item.class_id for item in found], [17, 8])
        self.assertAlmostEqual(found[0].x1, -8 / 32, places=4)

    def test_class_aware_suppression_and_argmax(self) -> None:
        raw = synthetic_head(width=1, height=1)
        raw[0, 16 + 0, 0, 0] = 5.0
        raw[0, 16 + 17, 0, 0] = 4.0
        found = self.compare([raw, raw.copy()], [32, 32], iou=0.5)
        self.assertEqual([item.class_id for item in found], [0, 17])
        argmax = self.compare([raw, raw.copy()], [32, 32], multi_label=False, iou=0.5)
        self.assertEqual([item.class_id for item in argmax], [0])

    def test_empty_nonfinite_and_task_filter(self) -> None:
        raw = synthetic_head()
        self.assertEqual(self.compare([raw], [16], confidence=0.5), [])
        raw[0, 16 + 0, 0, 0] = 5.0
        raw[0, 0, 0, 0] = np.nan
        raw[0, 16 + 9, 0, 1] = 5.0
        raw[0, 16 + 8, 1, 0] = np.inf
        found = self.compare([raw], [16])
        self.assertEqual([item.class_id for item in found], [9])
        c_array = (CDetection * len(found))(*found)
        count = self.library.v8_filter_classes(c_array, len(found), 9, 9, c_array)
        self.assertEqual(count, 1)
        self.assertEqual(len(filter_classes([Detection(
            item.x1, item.y1, item.x2, item.y2, item.score, item.class_id
        ) for item in found], 9, 9)), count)

    def test_letterbox_projection(self) -> None:
        sample = Detection(0.125, 0.25, 0.875, 0.75, 0.9, 10)
        metadata = Letterbox(640, 320, 416, 416, 0.65, 0.65, 0.0, 104.0)
        py = project_box(sample, metadata)
        self.assertAlmostEqual(py.x1, 80.0)
        self.assertAlmostEqual(py.y1, 0.0)
        c_sample = CDetection(*sample.__dict__.values())
        c_meta = CLetterbox(*metadata.__dict__.values())
        c_output = CDetection()
        self.assertEqual(self.library.v8_project_box(ctypes.byref(c_sample),
                                                      ctypes.byref(c_meta),
                                                      ctypes.byref(c_output)), 0)
        for name in ("x1", "y1", "x2", "y2"):
            self.assertAlmostEqual(getattr(py, name), getattr(c_output, name), places=5)

    def test_actual_three_scale_shape(self) -> None:
        heads = []
        for width in (52, 26, 13):
            raw = np.full((1, 82, width, width), -20.0, dtype=np.float32)
            for side in range(4):
                raw[0, side * 16 + 1] = 20.0
            heads.append(raw)
        heads[1][0, 64 + 17, 4, 7] = 8.0
        found = self.compare(heads, [8, 16, 32], input_size=416)
        self.assertEqual([item.class_id for item in found], [17])

    def test_actual_three_scale_nine_class_shape(self) -> None:
        heads = []
        for width in (52, 26, 13):
            raw = np.full((1, 73, width, width), -20.0, dtype=np.float32)
            for side in range(4):
                raw[0, side * 16 + 1] = 20.0
            heads.append(raw)
        heads[1][0, 64 + 8, 4, 7] = 8.0
        found = self.compare(heads, [8, 16, 32], input_size=416, classes=9)
        self.assertEqual([item.class_id for item in found], [8])

    def test_dense_global_cap_keeps_late_class(self) -> None:
        raw=synthetic_head(width=4,height=4)
        for cid in range(18):
            raw[0,16+cid]=1+cid*.1
        found=self.compare([raw],[8],cap=7,iou=.9)
        self.assertEqual(len(found),7)
        self.assertTrue(all(item.class_id==17 for item in found))

    def test_projection_odd_dimensions_and_outside_boxes(self) -> None:
        for width,height in [(239,237),(641,319),(319,641)]:
            scale=min(416/width,416/height)
            left=round((416-round(width*scale))/2-.1)
            top=round((416-round(height*scale))/2-.1)
            metadata=Letterbox(width,height,416,416,scale,scale,left,top)
            sample=Detection(-.1,.1,1.1,.9,.8,17)
            py=project_box(sample,metadata)
            c_sample=CDetection(*sample.__dict__.values());c_meta=CLetterbox(*metadata.__dict__.values());out=CDetection()
            self.assertEqual(self.library.v8_project_box(ctypes.byref(c_sample),ctypes.byref(c_meta),ctypes.byref(out)),0)
            for name in ('x1','y1','x2','y2'):
                self.assertAlmostEqual(getattr(py,name),getattr(out,name),places=3)


if __name__ == "__main__":
    unittest.main()
