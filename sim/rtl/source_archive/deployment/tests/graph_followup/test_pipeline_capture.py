"""In-process sender transport tests; zero sockets, inference or board access."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"tools"))
import capture_z100_pipeline_trace as c

TENSOR=bytes(c.TENSOR_BYTES)
INPUT={"path":"synthetic://one-rgb","bytes":len(TENSOR),"sha256":hashlib.sha256(TENSOR).hexdigest()}


class FakeClock:
    def __init__(self): self.now=0
    def __call__(self):
        self.now+=1000
        return self.now


def framed(value):
    raw=c.json_bytes(value)
    return struct.pack("!I",len(raw))+raw


def hello():
    return {"type":"HELLO_OK","protocol":c.PROTOCOL,"runtime":"host_reference",
        "model_sha256":c.analyzer.IDENTITY["package_sha256"],"classes_sha256":c.CLASSES_SHA,
        "class_count":9,"class_domain":"pin","input":"rgb-u8-640-letterbox114",
        "box_space":"normalized-model-xyxy"}


class FakeSocket:
    def __init__(self,clock,mode="ok"):
        self.clock=clock; self.mode=mode; self.state=0; self.pending=b""; self.rgb=0
        self.closed=False; self.timeouts=[]; self.result_ready=False; self.request=None

    def settimeout(self,seconds):
        if seconds <= 0: raise AssertionError("positive remaining timeout required")
        self.timeouts.append(seconds)

    def bind(self,address): self.bound=address

    def connect(self,address):
        self.endpoint=address
        if self.mode == "connect_failure": raise ConnectionError("synthetic refused")

    def sendall(self,data):
        if self.state < 2:
            raw=bytes(data); n=struct.unpack("!I",raw[:4])[0]
            if len(raw) != n+4: raise AssertionError("JSON send framing wrong")
            request=c.strict_json(raw[4:])
            if self.state == 0:
                if request["type"] != "HELLO": raise AssertionError("HELLO first")
                value=hello()
                if self.mode == "identity_failure": value["model_sha256"]="0"*64
                if self.mode == "runtime_failure": value["runtime"]="board"
                self.pending=framed(value)
                if self.mode == "oversized": self.pending=struct.pack("!I",c.MAX_JSON_BYTES+1)
                if self.mode == "duplicate_json":
                    body=b'{"type":"HELLO_OK","type":"HELLO_OK"}'
                    self.pending=struct.pack("!I",len(body))+body
                self.state=1
            else:
                if request["type"] != "INFER" or request["task"] != "pin" or request["tensor_bytes"] != c.TENSOR_BYTES:
                    raise AssertionError("INFER identity/count wrong")
                self.request=request; self.state=2
                if self.mode == "infer_write_failure": raise ConnectionError("partial INFER write")
        else:
            if len(data)>65536: raise AssertionError("bounded payload chunk required")
            if self.mode == "rgb_write_failure": raise ConnectionError("partial RGB write")
            self.rgb+=len(data)
            if self.rgb == c.TENSOR_BYTES:
                rid=self.request["request_id"]
                result={"type":"RESULT","protocol":c.PROTOCOL,"runtime":"host_reference",
                    "request_id":rid,"box_space":"normalized-model-xyxy",
                    "detections":[{"class_id":0,"score":0.8,"xyxy":[0.1,0.2,0.3,0.4]},
                                  {"class_id":8,"score":0.6,"xyxy":[0.5,0.6,0.7,0.8]}]}
                if self.mode == "wrong_request_id": result["request_id"]="f"*32
                if self.mode == "board_error": result.update(type="ERROR",message="synthetic rejection")
                if self.mode == "invalid_class": result["detections"][0]["class_id"]=9
                if self.mode == "bool_score": result["detections"][0]["score"]=True
                if self.mode == "bad_box": result["detections"][0]["xyxy"]=[0.8,0.2,0.1,0.4]
                self.pending=framed(result); self.result_ready=True
                if self.mode == "partial_result": self.pending=self.pending[:13]

    def recv(self,count):
        if self.result_ready and self.mode == "result_timeout": raise TimeoutError("synthetic response timeout")
        if self.result_ready and self.mode == "late_result" and len(self.pending) <= 17:
            self.clock.now+=2_000_000_000
        data=self.pending[:min(count,17)]
        self.pending=self.pending[len(data):]
        return data

    def close(self):
        self.closed=True
        if self.mode == "close_failure": raise OSError("synthetic close failure")


class MemoryJournal:
    def __init__(self): self.events=[]
    def emit(self,value): self.events.append(copy.deepcopy(value))
    def raw(self): return b"".join(c.json_bytes(e)+b"\n" for e in self.events)


class CaptureChecks(unittest.TestCase):
    def setUp(self):
        self.clock=FakeClock(); self.sockets=[]; self.ids=0
        self.plan={"endpoint":{"host":"192.0.2.1","port":5001,"local_address":"192.0.2.2"},
            "inputs":[dict(INPUT)],"frame_timeout_seconds":1.0,"trials":[list(v) for v in c.TRIALS]}

    def capture(self,mode="ok",trials=((-1,2),(0,3)),journal=None,load=None):
        def factory():
            sock=FakeSocket(self.clock,mode); self.sockets.append(sock); return sock
        def request_id():
            self.ids+=1; return f"{self.ids:032x}"
        self.journal=journal or MemoryJournal()
        with mock.patch.object(c.socket,"socket",side_effect=AssertionError("real socket forbidden")):
            return c.capture(self.plan,self.journal,capture_kind="synthetic",clock=self.clock,socket_factory=factory,
                load_input=load or (lambda r:TENSOR),request_id_factory=request_id,trials=trials)

    def test_complete_3020_fragmented_captures_analyze_and_stay_synthetic(self):
        trace=self.capture(trials=c.TRIALS)
        self.assertTrue(trace["capture_complete"])
        self.assertEqual(len(trace["frames"]),3020)
        self.assertEqual([sum(r["group"] == group for r in trace["frames"]) for group,_ in c.TRIALS],[20,1000,1000,1000])
        self.assertEqual(len(self.sockets),3020)
        self.assertTrue(all(s.closed and s.rgb == c.TENSOR_BYTES for s in self.sockets))
        report=c.analyzer.analyze(trace)
        self.assertEqual(report["trace_performance_gate"],"SIMULATION_ONLY")
        self.assertFalse(report["physical_30fps_accepted"])
        row=trace["frames"][0]
        self.assertLess(row["input_start_ns"],row["connected_ns"])
        self.assertLess(row["connected_ns"],row["hello_complete_ns"])
        self.assertLess(row["hello_complete_ns"],row["rgb_send_start_ns"])
        self.assertLess(row["rgb_send_start_ns"],row["rgb_send_end_ns"])
        self.assertLess(row["rgb_send_end_ns"],row["result_complete_ns"])
        self.assertLess(row["result_complete_ns"],row["terminal_ns"])
        self.assertNotIn("result_body_base64",row)
        raw=base64.b64decode(self.journal.events[2]["frame"]["result_body_base64"],validate=True)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),row["result_body_sha256"])
        self.assertEqual([d["class_id"] for d in c.strict_json(raw)["detections"]],[0,8])
        self.assertEqual(row["detections"],2)
        self.assertTrue(all(r["queue_depth_before"] == 0 for r in trace["frames"]))
        path=ARTIFACT_DIR/"complete_3020.ndjson"; path.write_bytes(self.journal.raw())
        recovered=c.recover_journal(path)
        self.assertTrue(recovered["capture_complete"])
        self.assertEqual(recovered["frames"],trace["frames"])
        result_dir=ARTIFACT_DIR/"complete_analysis"; result_dir.mkdir()
        self.assertEqual(c.write_capture_result(result_dir,recovered,path)["trace_performance_gate"],"SIMULATION_ONLY")
        # A crash after the last terminal but before the durable end must never
        # silently turn into a complete capture, even with all 3020 timestamps.
        path=ARTIFACT_DIR/"all_rows_missing_end.ndjson"
        path.write_bytes(b"".join(c.json_bytes(e)+b"\n" for e in self.journal.events[:-1]))
        recovered=c.recover_journal(path)
        self.assertFalse(recovered["capture_complete"])
        result_dir=ARTIFACT_DIR/"incomplete_analysis"; result_dir.mkdir()
        self.assertEqual(c.write_capture_result(result_dir,recovered,path)["trace_performance_gate"],"NOT_EVALUATED")

    def test_deadline_decreases_across_fragmented_io(self):
        self.capture(trials=((-1,1),))
        t=self.sockets[0].timeouts
        self.assertGreater(len(t),40)
        self.assertTrue(all(a>b>0 for a,b in zip(t,t[1:])))

    def test_errors_stop_at_first_attempt_and_never_retry(self):
        for mode in ["connect_failure","identity_failure","runtime_failure","oversized","duplicate_json",
            "infer_write_failure","rgb_write_failure","wrong_request_id","board_error","invalid_class",
            "bool_score","bad_box","partial_result","result_timeout","close_failure"]:
            with self.subTest(mode=mode):
                self.sockets=[]
                trace=self.capture(mode)
                self.assertEqual(len(trace["frames"]),1)
                self.assertEqual(len(self.sockets),1)
                self.assertTrue(self.sockets[0].closed)
                self.assertFalse(trace["capture_complete"])
                self.assertIn(trace["frames"][0]["status"],["error","dropped"])
                self.assertEqual(trace["stop_reason"],"first_error_no_retry")

    def test_partial_submission_or_result_is_unknown_and_dropped(self):
        for mode in ["infer_write_failure","rgb_write_failure","partial_result","result_timeout"]:
            with self.subTest(mode=mode):
                row=self.capture(mode)["frames"][0]
                self.assertEqual(row["status"],"dropped")
                self.assertTrue(row["outcome_unknown"])
                self.assertTrue(row["submission_attempted"])

    def test_known_board_rejection_is_error_with_raw_response(self):
        row=self.capture("board_error")["frames"][0]
        self.assertEqual(row["status"],"error")
        self.assertFalse(row["outcome_unknown"])
        self.assertEqual(c.strict_json(base64.b64decode(self.journal.events[2]["frame"]["result_body_base64"]))["type"],"ERROR")

    def test_hello_failure_has_no_rgb_or_infer_submission(self):
        row=self.capture("identity_failure")["frames"][0]
        self.assertFalse(row["submission_attempted"])
        self.assertEqual(self.sockets[0].rgb,0)
        self.assertIsNone(self.sockets[0].request)

    def test_late_final_fragment_cannot_pass_deadline(self):
        row=self.capture("late_result")["frames"][0]
        self.assertEqual(row["status"],"error")
        self.assertFalse(row["outcome_unknown"])
        self.assertGreater(row["terminal_ns"]-row["input_start_ns"],1_000_000_000)

    def test_rgb_identity_change_opens_no_socket(self):
        row=self.capture(load=lambda r:b"wrong")["frames"][0]
        self.assertEqual(row["status"],"error")
        self.assertFalse(row["submission_attempted"])
        self.assertFalse(self.sockets)

    def test_begin_journal_failure_prevents_socket_creation(self):
        class Broken(MemoryJournal):
            def emit(self,value):
                if value["event"] == "begin": raise OSError("disk full")
                super().emit(value)
        with self.assertRaises(OSError): self.capture(journal=Broken())
        self.assertFalse(self.sockets)

    def test_terminal_journal_failure_stops_before_next_request(self):
        class Broken(MemoryJournal):
            def emit(self,value):
                if value["event"] == "terminal": raise OSError("disk full")
                super().emit(value)
        with self.assertRaises(OSError): self.capture(journal=Broken())
        self.assertEqual(len(self.sockets),1)
        self.assertTrue(self.sockets[0].closed)

    def test_physical_trial_count_or_injected_clock_cannot_be_shortcut(self):
        with self.assertRaises(c.CaptureError):
            c.capture(self.plan,MemoryJournal(),capture_kind="physical_board",trials=((-1,1),))
        with self.assertRaises(c.CaptureError):
            c.capture(self.plan,MemoryJournal(),capture_kind="physical_board",clock=self.clock)

    def test_strict_json_rejects_duplicates_nan_and_invalid_encoding(self):
        for raw in [b'{"x":1,"x":2}',b'{"score":NaN}',b'{"score":Infinity}',b'\xff',b'{',
            '{"x":1}'.encode("utf16")]:
            with self.subTest(raw=raw),self.assertRaises(c.CaptureError): c.strict_json(raw)

    def test_bad_detection_contract_keeps_all_nine_classes(self):
        value={"type":"RESULT","protocol":c.PROTOCOL,"runtime":"host_reference","request_id":"0"*32,
            "box_space":"normalized-model-xyxy","detections":[]}
        for cls in range(9):
            value["detections"].append({"class_id":cls,"score":0.5,"xyxy":[0,0,1,1]})
        self.assertEqual(c.validate_result(value,"0"*32,"host_reference"),9)
        for mutate in [lambda v:v.update(detections=[{}]*301),lambda v:v["detections"][0].update(class_id=True),
            lambda v:v["detections"][0].update(score=float("nan")),lambda v:v["detections"][0].update(xyxy=[0,0,2,1])]:
            bad=copy.deepcopy(value); mutate(bad)
            with self.assertRaises(c.CaptureError): c.validate_result(bad,"0"*32,"host_reference")

    def test_journal_recovery_retains_pending_without_end_time(self):
        self.capture(trials=((-1,2),))
        events=copy.deepcopy(self.journal.events[:-1])
        pending={"frame_id":"a"*32,"group":0,"input_start_ns":self.clock.now+1,"queue_depth_before":0}
        events.append({"event":"begin","frame":pending})
        data=b"".join(c.json_bytes(e)+b"\n" for e in events)+b'{"event":"terminal"'
        path=ARTIFACT_DIR/"pending_torn.ndjson"; path.write_bytes(data)
        result=c.recover_journal(path)
        self.assertEqual(len(result["frames"]),2)
        self.assertEqual(result["pending_frames"],[pending])
        self.assertNotIn("terminal_ns",result["pending_frames"][0])
        self.assertTrue(result["torn_tail"])
        self.assertFalse(result["capture_complete"])

    def test_recovery_rejects_mismatched_terminal_and_late_events(self):
        self.capture(trials=((-1,1),))
        events=copy.deepcopy(self.journal.events)
        events[2]["frame"]["frame_id"]="f"*32
        path=ARTIFACT_DIR/"bad_terminal.ndjson"
        path.write_bytes(b"".join(c.json_bytes(e)+b"\n" for e in events))
        with self.assertRaises(c.CaptureError): c.recover_journal(path)
        path.write_bytes(self.journal.raw()+c.json_bytes({"event":"begin","frame":{}})+b"\n")
        with self.assertRaises(c.CaptureError): c.recover_journal(path)

    def test_real_durable_journal_matches_memory_capture(self):
        path=ARTIFACT_DIR/"durable.ndjson"
        journal=c.Journal(path)
        try: trace=self.capture(trials=((-1,1),),journal=journal)
        finally: journal.close()
        result=c.recover_journal(path)
        self.assertEqual(result["frames"],trace["frames"])
        self.assertFalse(result["capture_complete"])
        self.assertFalse(result["pending_frames"])

    def test_frozen_prepare_is_socket_free_and_hash_binds_input(self):
        rgb=ARTIFACT_DIR/"fixture_rgb.bin"; rgb.write_bytes(TENSOR)
        with mock.patch.object(c.socket,"socket",side_effect=AssertionError("prepare must not connect")):
            plan=c.prepare_plan("192.0.2.1",5001,[rgb])
            c.validate_plan(plan)
            with self.assertRaises(c.CaptureError): c.validate_plan(plan,require_dossier=True)
        self.assertEqual(plan["inputs"][0]["sha256"],INPUT["sha256"])
        rgb.write_bytes(b"x"*c.TENSOR_BYTES)
        with self.assertRaises(c.CaptureError): c.validate_plan(plan)

    def test_input_read_is_bounded_even_if_file_grows(self):
        rgb=ARTIFACT_DIR/"grown_rgb.bin"
        rgb.write_bytes(TENSOR+b"extra-data")
        self.assertEqual(len(c.load_rgb({"path":str(rgb)})),c.TENSOR_BYTES+1)

    def test_recovery_honors_explicit_incomplete_end(self):
        self.capture(trials=((-1,1),))
        self.journal.events[0]["trace"]["capture_plan"]["trials"]=[[-1,1]]
        self.journal.events[-1]["capture_complete"]=False
        path=ARTIFACT_DIR/"explicit_incomplete.ndjson"; path.write_bytes(self.journal.raw())
        self.assertFalse(c.recover_journal(path)["capture_complete"])


if __name__ == "__main__":
    ARTIFACT_DIR=Path(sys.argv[1]).resolve()
    if not ARTIFACT_DIR.is_relative_to(ROOT): raise ValueError("test artifacts outside project")
    ARTIFACT_DIR.mkdir(parents=True,exist_ok=False)
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(CaptureChecks)
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    print(stream.getvalue())
    summary={"status":"PASS_IN_PROCESS_SYNTHETIC_CAPTURE_ONLY" if result.wasSuccessful() else "FAIL",
        "tests":result.testsRun,"errors":len(result.errors),"failures":len(result.failures),
        "network_used":False,"board_access":False,"physical_30fps_accepted":False}
    (ARTIFACT_DIR/"test_result.json").write_bytes(c.json_bytes(summary)+b"\n")
    print(json.dumps(summary))
    sys.exit(0 if result.wasSuccessful() else 1)
