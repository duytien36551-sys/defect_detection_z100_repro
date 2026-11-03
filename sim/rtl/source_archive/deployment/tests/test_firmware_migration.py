"""Cross-layer migration checks for the 9-class and legacy 18-class paths."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from deployment.desktop.diagnostics import load_fpga_resources
from deployment.desktop.protocol import (BoardProtocolError, class_domain,
                                         validate_class_names, validate_detections)
from deployment.desktop.preprocess import ImageMapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = PROJECT_ROOT / "deployment" / "firmware"
FIRMWARE_COPIES = (
    FIRMWARE,
    PROJECT_ROOT / "deployment" / "candidates" / "tile64" / "firmware",
)
PCB_NAMES = ["PCB_SH", "PCB_SP", "PCB_SC", "PCB_OP", "PCB_MB", "PCB_HB",
             "PCB_CS", "PCB_CFO", "PCB_BMFO"]
PIN_NAMES = ["PIN_破损", "PIN_裂痕", "PIN_击穿", "PIN_薄膜破损", "PIN_电极缺失",
             "PIN_异物", "PIN_有机物污染", "PIN_部分缺失", "PIN_冗余"]


class FirmwareMigrationTests(unittest.TestCase):
    def test_class_domain_mapping_supports_zero_based_pin_and_legacy_joint(self) -> None:
        pcb = PCB_NAMES
        pin = PIN_NAMES
        joint = PCB_NAMES + PIN_NAMES
        self.assertEqual(class_domain(validate_class_names(pin)[0]), "pin")
        self.assertEqual(validate_class_names(joint), joint)
        mapping = ImageMapping(416, 416, 1.0, 0, 0, 416, 416)
        raw = [{"class_id": 0, "score": 0.8, "xyxy": [0.1, 0.1, 0.3, 0.3]}]
        rows = validate_detections(raw, mapping, "all", pin)
        self.assertEqual([row["class_id"] for row in rows], [0])
        with self.assertRaisesRegex(BoardProtocolError, "does not match"):
            validate_detections(raw, mapping, "pcb", pin)
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_class_names(["PCB_SH"] * 9)
        with self.assertRaisesRegex(ValueError, "nine-class names"):
            validate_class_names(pcb[:8] + ["not-a-domain-class"])
        with self.assertRaisesRegex(ValueError, "exactly nine"):
            validate_class_names(pcb[:8])

    def test_old_7020_report_is_not_shown_as_the_unselected_7z100_target(self) -> None:
        default = load_fpga_resources()
        self.assertFalse(default["available"])
        self.assertEqual(default["metrics"], [])
        self.assertIn("未评估", default["note"])
        self.assertIn("7020", default["note"])

        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "old.rpt"
            report.write_text("Design State : Routed\n| Device : xc7z020clg400-2 |\n", encoding="utf-8")
            selected = load_fpga_resources(target_device="xc7z100-2ffg900i", report_path=report)
        self.assertFalse(selected["available"])
        self.assertEqual(selected["metrics"], [])
        self.assertIn("does not match", selected["note"])

    def test_c_package_identity_and_decode_shape_reject_mismatches(self) -> None:
        harness = r'''#include "v8_pipeline.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum { INPUT_BYTES=3*416*416, NODE_COUNT=3, MAX_PARAMS=12000,
       MAX_ARENA=400000, MAX_SCRATCH=220000, MAX_HEADS=300000 };
static V8Node nodes[NODE_COUNT];
static V8Graph graph;
static V8Runtime runtime;
static V8Pipeline pipeline;
static int8_t input[INPUT_BYTES], params[MAX_PARAMS], arena[MAX_ARENA];
static int32_t scratch[MAX_SCRATCH];
static float heads[MAX_HEADS];
static V8Detection detections[300];
static uint8_t package[32+MAX_PARAMS];

static void put32(uint8_t *p,uint32_t v){p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8);p[2]=(uint8_t)(v>>16);p[3]=(uint8_t)(v>>24);}
static uint32_t crc32(const uint8_t*p,size_t n){uint32_t c=~0u;size_t i;int j;for(i=0;i<n;i++){c^=p[i];for(j=0;j<8;j++)c=(c>>1)^(0xedb88320u&(0u-(c&1u)));}return ~c;}
static int conv(void*o,const V8Node*n,const V8Node*s,const int8_t*x,const int8_t*w,const uint8_t*b,int32_t*out){size_t i,count=(size_t)n->c*n->h*n->w;(void)o;(void)s;(void)x;(void)w;(void)b;for(i=0;i<count;i++)out[i]=0;return 0;}
static size_t make_graph(int bad_head){
    const uint32_t widths[3]={52,26,13};uint32_t i,arena_at=0,param_at=0;
    memset(nodes,0,sizeof(nodes));memset(params,0,sizeof(params));memset(&graph,0,sizeof(graph));
    for(i=0;i<NODE_COUNT;i++){
        uint32_t channels=4u*16u+9u+(bad_head&&i==1u?9u:0u);
        size_t elements=(size_t)channels*widths[i]*widths[i];
        nodes[i].op=V8_CONV;nodes[i].c=channels;nodes[i].h=nodes[i].w=widths[i];
        nodes[i].offset=arena_at;nodes[i].bytes=(uint32_t)elements;nodes[i].inputs[0]=-1;
        nodes[i].count=1;nodes[i].kernel=1;nodes[i].stride=416u/widths[i];nodes[i].groups=1;nodes[i].scale=1.0;
        nodes[i].weight=param_at;param_at+=channels*3u;nodes[i].bias=param_at;param_at+=channels*4u;
        nodes[i].multiplier=param_at;param_at+=channels*8u;
        for(uint32_t c=0;c<channels;c++){double one=1.0;memcpy(params+nodes[i].multiplier+c*8u,&one,8);}
        graph.outputs[i]=i;arena_at+=(uint32_t)elements;
    }
    graph.nodes=nodes;graph.count=NODE_COUNT;graph.arena_bytes=arena_at;graph.param_bytes=param_at;
    graph.param_crc=crc32((const uint8_t*)params,param_at);graph.input_scale=1.0;
    graph.classes=9;graph.reg_max=16;graph.input_size=416;
    return param_at;
}
static size_t make_package(size_t param_bytes,uint32_t classes,uint32_t input_size){
    memset(package,0,sizeof(package));memcpy(package,"V8PK",4);put32(package+4,1);put32(package+8,(uint32_t)param_bytes);
    put32(package+12,graph.param_crc);put32(package+16,graph.count);put32(package+20,graph.arena_bytes);
    put32(package+24,classes);put32(package+28,input_size);memcpy(package+32,params,param_bytes);
    return 32u+param_bytes;
}
static void setup_runtime(void){
    memset(arena,0,sizeof(arena));memset(&runtime,0,sizeof(runtime));memset(&pipeline,0,sizeof(pipeline));
    runtime.graph=&graph;runtime.params=(const uint8_t*)params;runtime.param_size=graph.param_bytes;
    runtime.arena=arena;runtime.arena_size=sizeof(arena);runtime.scratch=scratch;runtime.scratch_count=MAX_SCRATCH;
    runtime.conv=conv;pipeline.runtime=&runtime;pipeline.input_nchw=input;pipeline.input_capacity=sizeof(input);
    pipeline.heads_float=heads;pipeline.heads_capacity=MAX_HEADS;
    pipeline.decode=(V8DecodeConfig){416,416,9,16,.99f,.45f,1,0,0};
}
int main(void){const uint8_t *payload=(const uint8_t*)1;int rc;size_t params_size=make_graph(0),package_size;
    package_size=make_package(params_size,9,416);
    if(v8_package_open(package,package_size,&graph,&payload)||payload!=package+32)return 1;
    payload=(const uint8_t*)1;make_package(params_size,18,416);
    if(v8_package_open(package,package_size,&graph,&payload)==0||payload!=0)return 2;
    payload=(const uint8_t*)1;make_package(params_size,9,320);
    if(v8_package_open(package,package_size,&graph,&payload)==0||payload!=0)return 3;
    graph.reg_max=15;payload=(const uint8_t*)1;make_package(params_size,9,416);
    if(v8_package_open(package,package_size,&graph,&payload)==0||payload!=0)return 4;
    graph.reg_max=16;setup_runtime();
    rc=v8_pipeline_infer(&pipeline,(const uint8_t*)input,INPUT_BYTES,detections,300,(size_t[]){0});
    if(rc!=0)return 5;
    params_size=make_graph(1);graph.param_crc=crc32((const uint8_t*)params,params_size);
    setup_runtime();
    {size_t count=99;rc=v8_pipeline_infer(&pipeline,(const uint8_t*)input,INPUT_BYTES,detections,300,&count);
     if(rc!=-5||count!=0)return 6;}
    puts("C 9-class V8PK identity and decode shape mismatch: PASS");return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "firmware_migration.c"
            source.write_text(harness, encoding="utf-8")
            for index, firmware in enumerate(FIRMWARE_COPIES):
                executable = Path(directory) / f"firmware_migration_{index}.exe"
                subprocess.run([
                    "gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
                    "-I", str(firmware), str(source),
                    str(firmware / "v8_runtime.c"), str(firmware / "v8_pipeline.c"),
                    str(firmware / "v8_decode.c"), "-lm", "-o", str(executable),
                ], check=True, capture_output=True, text=True)
                completed = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
                with self.subTest(firmware=firmware.relative_to(PROJECT_ROOT)):
                    self.assertIn("C 9-class V8PK identity and decode shape mismatch: PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
