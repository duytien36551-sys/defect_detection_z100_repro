"""Host preflight and private exact paired-product native MAC XSim/OOC screen.
Default is host-only; vendor work requires --execute --vendor-slot-released.
No route, board, production, or throughput acceptance is performed.
"""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, re, shutil, subprocess, sys, uuid
from datetime import datetime, timezone
from pathlib import Path
for _key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS'):
 os.environ[_key]='1'
ROOT=Path(__file__).resolve().parents[1]
HW=ROOT/'deployment/hardware/z100_2026/window_mac_packed_v1'
CORE=HW/'z100_window_mac.sv'; TB4=HW/'tb_z100_window_mac.sv'; TBS=HW/'tb_z100_window_mac_scale.sv'
PAIR=ROOT/'deployment/hardware/z100_2026/int8_pair_packing_v3/z100_int8_pair_packing.sv'
PAIR_REPORT=ROOT/'validation/board_z100/int8_pair_packing_v3/20261024T044617.750422Z/result.json'
PAIR_TB=ROOT/'deployment/hardware/z100_2026/int8_pair_packing_v3/tb_z100_int8_pair_packing.sv'
PAIR_VALIDATOR=ROOT/'tools/validate_z100_int8_pair_packing_v3.py'
BASE=ROOT/'deployment/hardware/z100_2026/window_mac_v1/z100_window_mac.sv'
BASE_TB4=ROOT/'deployment/hardware/z100_2026/window_mac_v1/tb_z100_window_mac.sv'
BASE_TBS=ROOT/'deployment/hardware/z100_2026/window_mac_scale_v1/tb_z100_window_mac_scale.sv'
SCALE=ROOT/'tools/validate_z100_window_mac_scale.py'
VIVADO=Path('C:/appload/2026.1/Vivado/bin')
MACRO=Path('C:/appload/2026.1/Vivado/data/verilog/src/unimacro/MULT_MACRO.v')
DSP_MODEL=Path('C:/appload/2026.1/Vivado/data/verilog/src/unisims/DSP48E1.v')
GLBL=Path('C:/appload/2026.1/Vivado/data/verilog/src/glbl.v')
PART='xc7z100ffg900-2'; PAIR_SHA='ee927bfd9e937855fd75f17b82b078f23532d5159d395aebc3b71063160067ad'
BASE_SHA='c2de472f539276da097e5ccd5bc7d44f2695dbff55ecb73458ea0105accbb643'
S4_EXPECT={'jobs':50,'replays':25,'raw_words':5152,'overflow_flags':5152,'metadata_sites':161,
 'stalls':408,'stream_errors':3,'config_errors':7,'run_errors':6,'cross_checks':297,
 'saturation_checks':377,'cancel_offsets':5,'reset_offsets':5,'max_groups':1024}

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rel(p):
 p=Path(p).resolve()
 try:return p.relative_to(ROOT.resolve()).as_posix()
 except ValueError:return 'external/'+p.drive.rstrip(':')+'/'+p.relative_to(p.anchor).as_posix()
def brace(p):
 s=Path(p).resolve().as_posix()
 if '{' in s or '}' in s: raise ValueError('Tcl path braces unsupported')
 return '{'+s+'}'
def load_scale():
 spec=importlib.util.spec_from_file_location('native_mac_scale_helper',SCALE)
 if spec is None or spec.loader is None: raise RuntimeError('Cannot load frozen scale helper')
 mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
def paths(scale):
 values=[*scale.source_paths(),Path(__file__).resolve(),BASE_TB4,CORE,TB4,TBS,PAIR,PAIR_TB,PAIR_VALIDATOR,PAIR_REPORT,MACRO,DSP_MODEL,GLBL]
 return tuple(dict.fromkeys(Path(x).resolve() for x in values))
def check_pair_proof():
 d=json.loads(PAIR_REPORT.read_text(encoding='utf-8'))
 if d.get('status')!='PASS_PRIVATE_EXACT_SIGNED_PAIR_HOST_XSIM_ONE_DSP_OOC_ONLY' or sha(PAIR)!=PAIR_SHA:
  raise ValueError('Frozen exact pair proof or source identity mismatch')
 hashes=d.get('source_sha256_before',{})
 if [v for k,v in hashes.items() if Path(k).name==PAIR.name]!=[PAIR_SHA]: raise ValueError('Pair proof does not bind frozen RTL')
 c=d.get('synthesis',{}).get('primitive_counts',{}); modes=d.get('synthesis',{}).get('dsp_modes',[])
 if d.get('simulation',{}).get('status')!='PASS' or c.get('DSP')!=1 or len(modes)!=1 or modes[0][1]!='MULTIPLY':
  raise ValueError('Frozen pair primitive lacks full XSim/single-MULTIPLY census')
 return {'status':d['status'],'rtl_sha256':PAIR_SHA,'report_sha256':sha(PAIR_REPORT),
         'triples':d.get('host',{}).get('triples'),'rtl_pairs':d.get('simulation',{}).get('output_pairs'),
         'primitive_counts':c,'dsp_modes':modes}
def check_scope():
 base=BASE.read_text(encoding='utf-8'); core=CORE.read_text(encoding='utf-8')
 if base[:base.index(');')+2]!=core[:core.index(');')+2]: raise ValueError('Native public interface changed')
 old='''                product_q[site][lane][0]<=activation_operand_q[site][lane/8][0]*$signed(weight_operand_q[0][lane*8+:8]);
                product_q[site][lane][1]<=activation_operand_q[site][lane/8][1]*$signed(weight_operand_q[1][lane*8+:8]);
                product_q[site][lane][2]<=activation_operand_q[site][lane/8][2]*$signed(weight_operand_q[2][lane*8+:8]);
                product_q[site][lane][3]<=activation_operand_q[site][lane/8][3]*$signed(weight_operand_q[3][lane*8+:8]);
'''
 if old in core or '(* use_dsp="yes" *) reg signed [15:0] product_q' in core: raise ValueError('Old direct product stage remains')
 needed=['wire signed [15:0] product_q[0:SITES-1][0:31][0:3];',
         'z100_int8_pair_packing packed_products (','.in_valid(1\'b1)',
         '.rst_n(1\'b1), .cancel(1\'b0)',
         'packed_pair<16','packed_tap<4']
 if any(x not in core for x in needed): raise ValueError('Packed product generator/tie-off is incomplete')
 if TB4.read_text(encoding='utf-8') != BASE_TB4.read_text(encoding='utf-8').replace(
  '    initial begin\n        repeat(3) step();@(negedge clk);rst_n=1;\n',
  '    initial begin\n        // Give vendor global primitives their required startup interval.\n        #250;\n        repeat(3) step();@(negedge clk);rst_n=1;\n'):
  raise ValueError('SITES4 testbench is not the frozen suite with only its startup delay added')
 if TBS.read_text(encoding='utf-8') != BASE_TBS.read_text(encoding='utf-8').replace(
  '    initial begin\n        $readmemh("fixture/firstconv_weights.hex", real_weight_bytes);\n',
  '    initial begin\n        // Keep both parameterized instances idle through vendor global startup.\n        #250;\n        $readmemh("fixture/firstconv_weights.hex", real_weight_bytes);\n'):
  raise ValueError('Scale testbench is not frozen suite plus startup delay only')
 return {'native_interface_unchanged':True,'direct_product_multipliers_removed':True,
         'pair_instances_per_site':64,'activation_replicas_and_native_sum_stages_retained':True,
         'testbench_changes':'250 ns startup delay only'}
def snapshot(src,dst):
 copied={}
 for p in src:
  if not p.is_file(): raise FileNotFoundError(f'Missing source/dependency: {p}')
  out=dst/rel(p); out.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,out); copied[rel(p)]=sha(out)
 return copied
def env_one():
 e=dict(os.environ)
 for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS'):e[k]='1'
 return e
def run(name,argv,cwd,evidence,result):
 p=subprocess.run(list(map(str,argv)),cwd=cwd,env=env_one(),text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=False)
 out=p.stdout;(evidence/(name+'.log')).write_text(out,encoding='utf-8',newline='\n')
 result['commands'].append({'name':name,'args':list(map(str,argv)),'return_code':p.returncode,'cwd':str(cwd)})
 if p.returncode:raise RuntimeError(f'{name} returned {p.returncode}')
 if re.search(r'^\s*(?:Fatal:|FATAL:|ERROR:)',out,re.M):raise RuntimeError(f'{name} emitted fatal/error diagnostic')
 return out
def check_s4(out):
 m=re.findall(r'^WINDOW_MAC_PASS\s+([^\r\n]+)',out,re.M)
 if len(m)!=1 or re.search(r'(?:Fatal:|FATAL:)',out):raise ValueError('SITES4 suite pass marker missing/duplicated')
 v={k:int(x) for k,x in re.findall(r'([a-zA-Z0-9_]+)=(\d+)',m[0])}
 for k,want in S4_EXPECT.items():
  if v.get(k)!=want:raise ValueError(f'SITES4 {k}={v.get(k)!r}, expected {want}')
 if v['raw_words']!=v['overflow_flags']:raise ValueError('SITES4 overflow flag coverage differs from output count')
 return {'status':'PASS','coverage':v,'checks':['all result words and overflow flags','metadata','output stalls','config/run/stream rejection','five cancel/reset offsets','INT32 recovery/saturation','resident weight replay']}

def write_tcl(evidence,build):
 p=evidence/'synth_sites12.tcl'
 t=r'''set_param general.maxThreads 2
if {![string match 2026.1* [version -short]]} {error "Requires Vivado 2026.1"}
read_verilog -sv @PAIR@ @CORE@
synth_design -top z100_window_mac -part xc7z100ffg900-2 -mode out_of_context -flatten_hierarchy none -generic {SITES=12}
create_clock -name mac_clk -period 10.000 [get_ports clk]
report_utilization -file @UTIL@
report_utilization -hierarchical -file @HIER@
report_timing_summary -delay_type min_max -report_unconstrained -file @TIMING@
write_checkpoint -force @DCP@
set lut [llength [get_cells -quiet -hier -filter {REF_NAME =~ LUT*}]]
set ff [llength [get_cells -quiet -hier -filter {REF_NAME =~ FD*}]]
set r36 [get_cells -quiet -hier -filter {REF_NAME =~ RAMB36*}]
set r18 [get_cells -quiet -hier -filter {REF_NAME =~ RAMB18*}]
set n36 [llength $r36]; set n18 [llength $r18]
set bram [expr {$n36 + ($n18 / 2.0)}]
set dsps [get_cells -quiet -hier -filter {REF_NAME =~ DSP*}]
set d48 [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}]
set latch [llength [get_cells -quiet -hier -filter {REF_NAME =~ LD*}]]
set black [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]
array set mc {}
set f [open @DSP@ w]; puts $f "cell\tAREG\tBREG\tMREG\tPREG\tUSE_MULT\tUSE_SIMD"
foreach c $d48 {
 set name [get_property NAME $c]; set vals {}
 foreach prop {AREG BREG MREG PREG USE_MULT USE_SIMD} {
  set v [get_property -quiet $prop $c]; if {$v eq ""} {set v UNAVAILABLE}; lappend vals $v
 }
 set mode [string toupper [lindex $vals 4]]; if {![info exists mc($mode)]} {set mc($mode) 0}; incr mc($mode)
 puts $f [join [concat [list $name] $vals] "\t"]
}; close $f
set owners [open @BRAM@ w]; puts $owners "cell\tprimitive\tweight_bank"
array set bc {0 0 1 0 2 0 3 0}; set unmatched 0
foreach c [concat $r36 $r18] {
 set name [get_property NAME $c]; set prim [get_property REF_NAME $c]
 if {[regexp {gen_weights\[([0-3])\]} $name m bank]} {incr bc($bank)} else {set bank UNMATCHED; incr unmatched}
 puts $owners "$name\t$prim\t$bank"
}; close $owners
set mult 0; set none 0; set other 0
foreach mode [array names mc] {if {$mode eq "MULTIPLY"} {set mult $mc($mode)} elseif {$mode eq "NONE"} {set none $mc($mode)} else {incr other $mc($mode)}}
set f [open @OBS@ w]
puts $f "DSP_TOTAL [llength $dsps]"; puts $f "DSP48E1_COUNT [llength $d48]"
puts $f "DSP_MULTIPLY_COUNT $mult"; puts $f "DSP_NONE_COUNT $none"; puts $f "DSP_OTHER_MODE_COUNT $other"
puts $f "LUT_COUNT $lut"; puts $f "FF_COUNT $ff"; puts $f "RAMB36E1_COUNT $n36"; puts $f "RAMB18E1_COUNT $n18"
puts $f "BRAM36_EQ $bram"; puts $f "LATCH_COUNT $latch"; puts $f "BLACKBOX_COUNT [llength $black]"; puts $f "BRAM_OWNER_UNMATCHED $unmatched"
for {set i 0} {$i<4} {incr i} {puts $f "BRAM_OWNER_BANK$i $bc($i)"}; close $f
puts "WINDOW_MAC_PACKED_SYNTH sites=12 version=[version -short] part=xc7z100ffg900-2 lut=$lut ff=$ff ram36=$n36 ram18=$n18 bram36eq=$bram dsp_total=[llength $dsps] dsp48=[llength $d48] dsp_multiply=$mult dsp_none=$none dsp_other=$other latches=$latch blackbox=[llength $black] bram_unmatched=$unmatched bank0=$bc(0) bank1=$bc(1) bank2=$bc(2) bank3=$bc(3)"
if {$lut>90000 || $ff>60000 || $bram<28.0 || $bram>40.0 || [llength $dsps]>1152 || [llength $dsps]!=[llength $d48] || $mult!=768 || $none>384 || $other!=0 || $latch!=0 || [llength $black]!=0 || $unmatched!=0 || $bc(0)==0 || $bc(1)==0 || $bc(2)==0 || $bc(3)==0} {error "Fixed packed-MAC OOC component gate failed"}
exit
'''
 for a,b in {'@PAIR@':brace(PAIR),'@CORE@':brace(CORE),'@UTIL@':brace(evidence/'utilization_sites12.rpt'),
  '@HIER@':brace(evidence/'hierarchical_utilization_sites12.rpt'),'@TIMING@':brace(evidence/'timing_unplaced_diagnostic_sites12.rpt'),
  '@DCP@':brace(build/'sites12_post_synth.dcp'),'@DSP@':brace(evidence/'dsp48e1_sites12.tsv'),
  '@BRAM@':brace(evidence/'bram_owner_sites12.tsv'),'@OBS@':brace(evidence/'observability_sites12.txt')}.items():t=t.replace(a,b)
 p.write_text(t,encoding='utf-8',newline='\n'); return p

def parse_ooc(out,evidence,build):
 pat=(r'^WINDOW_MAC_PACKED_SYNTH sites=12 version=(\S+) part=(\S+) lut=(\d+) ff=(\d+) ram36=(\d+) ram18=(\d+) '
  r'bram36eq=([0-9.]+) dsp_total=(\d+) dsp48=(\d+) dsp_multiply=(\d+) dsp_none=(\d+) dsp_other=(\d+) '
  r'latches=(\d+) blackbox=(\d+) bram_unmatched=(\d+) bank0=(\d+) bank1=(\d+) bank2=(\d+) bank3=(\d+)\s*$')
 m=re.findall(pat,out,re.M)
 if len(m)!=1:raise ValueError('Vivado did not emit exactly one anchored SITES12 OOC census marker')
 keys=('vivado_version','part','lut','ff','ram36','ram18','bram36_equivalent','dsp_total','dsp48e1','dsp_multiply','dsp_none','dsp_other_modes','latches','blackboxes','bram_owner_unmatched','bram_owner_bank0','bram_owner_bank1','bram_owner_bank2','bram_owner_bank3')
 d={k:(float(v) if k=='bram36_equivalent' else v if k in ('vivado_version','part') else int(v)) for k,v in zip(keys,m[0])}
 if not d['vivado_version'].startswith('2026.1') or d['part']!=PART:raise ValueError('Wrong Vivado version or device')
 if (d['dsp_total']!=d['dsp48e1'] or d['dsp_total']>1152 or d['dsp_multiply']!=768 or d['dsp_none']>384 or d['dsp_other_modes']):raise ValueError('Packed DSP count/mode gate failed')
 if not 28<=d['bram36_equivalent']<=40 or d['lut']>90000 or d['ff']>60000 or d['latches'] or d['blackboxes']:raise ValueError('BRAM/LUT/FF/latch/blackbox screen failed')
 if d['bram_owner_unmatched'] or any(d[f'bram_owner_bank{i}']<=0 for i in range(4)):raise ValueError('Weight BRAM ownership gate failed')
 rows=(evidence/'dsp48e1_sites12.tsv').read_text(encoding='utf-8').splitlines()
 if not rows or rows[0].split('\t')!=['cell','AREG','BREG','MREG','PREG','USE_MULT','USE_SIMD']:raise ValueError('DSP table header missing')
 cells=[]
 for row in rows[1:]:
  f=row.split('\t')
  if len(f)!=7:raise ValueError('Malformed DSP census row')
  cells.append({'name':f[0],'areg':f[1],'breg':f[2],'mreg':f[3],'preg':f[4],'mode':f[5].upper(),'simd':f[6]})
 mult=[c for c in cells if c['mode']=='MULTIPLY']; none=[c for c in cells if c['mode']=='NONE']; other=[c for c in cells if c['mode'] not in ('MULTIPLY','NONE')]
 if len(cells)!=d['dsp_total'] or len(mult)!=768 or len(none)!=d['dsp_none'] or other or any('packed_multiplier' not in c['name'] for c in mult):raise ValueError('Detailed DSP census does not prove 768 packed macro multipliers')
 if any('.gen_lane[' not in c['name'] or '.sum_q_reg' not in c['name'] for c in none):raise ValueError('USE_MULT=NONE DSP is not owned by native sum registers')
 br=(evidence/'bram_owner_sites12.tsv').read_text(encoding='utf-8').splitlines()
 if not br or br[0].split('\t')!=['cell','primitive','weight_bank']:raise ValueError('BRAM table header missing')
 bc={str(i):0 for i in range(4)}
 for row in br[1:]:
  f=row.split('\t')
  if len(f)!=3 or f[2] not in bc:raise ValueError('Unmatched BRAM owner')
  bc[f[2]]+=1
 if len(br)!=d['ram36']+d['ram18']+1 or sum(bc.values())!=d['ram36']+d['ram18']:raise ValueError('Detailed RAM primitive totals do not reconcile')
 if any(bc[str(i)]!=d[f'bram_owner_bank{i}'] for i in range(4)):raise ValueError('BRAM bank owner counts differ')
 for name in ('utilization_sites12.rpt','hierarchical_utilization_sites12.rpt','timing_unplaced_diagnostic_sites12.rpt','observability_sites12.txt'):
  if not (evidence/name).is_file():raise ValueError(f'Missing Vivado report {name}')
 dcp=build/'sites12_post_synth.dcp'
 if not dcp.is_file() or dcp.stat().st_size<100000:raise ValueError('Post-synthesis checkpoint absent/truncated')
 d.update(status='PASS_OOC_UNPLACED_COMPONENT_SCREEN_ONLY',dsp_modes={'MULTIPLY':len(mult),'NONE':len(none)},
  multiply_owner='packed_products.packed_multiplier',sum_none_owner='gen_site/gen_lane/sum_q_reg',
  detailed_bram_owner_counts=bc,dcp_sha256=sha(dcp),dcp_bytes=dcp.stat().st_size,clock_period_ns=10.0,route_attempted=False)
 return d

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--execute',action='store_true',help='run SITES4 and SITES8/12 XSim, followed by SITES12 OOC')
 ap.add_argument('--vendor-slot-released',action='store_true',help='root has released one vendor slot')
 a=ap.parse_args()
 if a.execute!=a.vendor_slot_released:ap.error('--execute and --vendor-slot-released are required together')
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]
 ev=ROOT/'validation/board_z100/window_mac_packed_v1'/stamp
 build=ROOT/'deployment/build/z100_window_mac_packed_v1'/stamp
 ev.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
 helper=load_scale(); src=paths(helper); before={rel(p):sha(p) for p in src}; report=ev/'result.json'
 result={'schema':'z100-window-mac-packed/1','status':'RUNNING','run_id':stamp,
  'scope':'Exact paired-product native MAC XSim and SITES12 OOC census only; no route, board, production, or FPS claim',
  'source_sha256_before':before,'source_snapshot':str(ev/'source_snapshot'),'device_part':PART,
  'sites4_expected':S4_EXPECT,'sites12_expected':{'jobs':86,'words':17344,'metadata':542,'cross':768,'saturation':768,'max_groups':1024},
  'limits':{'sites12_dsp_multiply_exact':768,'sites12_dsp_none_max':384,'sites12_dsp_total_max':1152,
   'bram36_equivalent':[28,40],'lut_max':90000,'ff_max':60000,'latches':0,'blackboxes':0},
  'toolchain':{'python':sys.executable,'vivado_bin':str(VIVADO),'max_vendor_threads':2,'numerical_threads':1},
  'board_access':False,'route_attempted':False,'bitstream_created':False,'production_integrated':False,
  'vendor_attempted':False,'commands':[]}
 try:
  if before[rel(BASE)]!=BASE_SHA or before[rel(PAIR)]!=PAIR_SHA:raise ValueError('Frozen RTL SHA mismatch')
  result['pair_primitive_proof']=check_pair_proof()
  result['source_scope_preflight']=check_scope()
  snap=snapshot(src,ev/'source_snapshot')
  if snap!=before:raise ValueError('Source snapshot hash inventory mismatch')
  model=helper.validate_model_inputs()
  result['model_identity']={k:v for k,v in model.items() if k!='payload'}
  result['firstconv_fixture']=helper.create_firstconv_fixture(build,model)
  result['host_preflight']={'status':'PASS_HOST_FIXTURE_ONLY','original_OIHW_bias_NCHW_golden':True,
   'native_weight_layout_crosscheck':True,'fixture_hashes':result['firstconv_fixture']['generated_fixture'],
   'parity_result_sha256':helper.sha(helper.PARITY_RESULT.read_bytes()),
   'package_sha256':sha(helper.PACKAGE),'NCHW_sha256':sha(helper.NCHW_INPUT),
   'native_weight_manifest_sha256':sha(helper.NATIVE_MANIFEST)}
  if a.execute:
   for tool in ('xvlog.bat','xelab.bat','xsim.bat','vivado.bat'):
    if not (VIVADO/tool).is_file():raise FileNotFoundError(f'Missing vendor tool {VIVADO/tool}')
   if sha(MACRO)!='d8ad46e2f5c808f52d4029025695ff7f67d6526c009bcaba0a75e84eecc27a2c':raise ValueError('MULT_MACRO source SHA mismatch')
   result['vendor_attempted']=True
   s4=build/'sim_sites4';s4.mkdir()
   run('xvlog_sites4',[VIVADO/'xvlog.bat','-sv',CORE,PAIR,TB4,GLBL],s4,ev,result)
   run('xelab_sites4',[VIVADO/'xelab.bat','-mt','2','-L','unimacro_ver','-L','unisims_ver','tb_z100_window_mac','glbl','-s','window_mac_packed_s4_sim'],s4,ev,result)
   result['simulation_sites4']=check_s4(run('xsim_sites4',[VIVADO/'xsim.bat','window_mac_packed_s4_sim','-runall'],s4,ev,result))
   ss=build/'sim_scale';ss.mkdir();shutil.copytree(build/'fixture',ss/'fixture')
   run('xvlog_scale',[VIVADO/'xvlog.bat','-sv',CORE,PAIR,TBS,GLBL],ss,ev,result)
   run('xelab_scale',[VIVADO/'xelab.bat','-mt','2','-L','unimacro_ver','-L','unisims_ver','tb_z100_window_mac_scale','glbl','-s','window_mac_packed_scale_sim'],ss,ev,result)
   result['simulation_scale']=helper.check_simulation(run('xsim_scale',[VIVADO/'xsim.bat','window_mac_packed_scale_sim','-runall'],ss,ev,result))
   tcl=write_tcl(ev,build)
   syn=run('vivado_ooc_sites12',[VIVADO/'vivado.bat','-mode','batch','-log',ev/'vivado_sites12.log','-journal',ev/'vivado_sites12.jou','-source',tcl],build,ev,result)
   result['synthesis_sites12']=parse_ooc(syn,ev,build)
   result['status']='PASS_XSIM_AND_OOC_COMPONENT_SCREENS_ONLY'
  else:
   result['status']='PASS_HOST_PREFLIGHT_VENDOR_PENDING';result['vendor_status']='NOT_RUN_NO_EXPLICIT_SLOT_RELEASE'
 except Exception as ex:
  result['status']='FAILED_CLOSED';result['error']=f'{type(ex).__name__}: {ex}'
 finally:
  after={rel(p):sha(p) for p in src if p.is_file()};result['source_sha256_after']=after
  result['source_hashes_unchanged']=after==before
  if after!=before:result.update(status='FAILED_SOURCE_INTEGRITY',error='Source/dependency changed during validation')
  result['artifact_sha256']={rel(p):sha(p) for base in (ev,build) for p in sorted(base.rglob('*')) if p.is_file() and p!=report}
  report.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
 print(json.dumps({'status':result['status'],'report':str(report),'error':result.get('error'),'vendor_attempted':result['vendor_attempted']},indent=2),flush=True)
 return 0 if result['status'].startswith('PASS_') else 2

if __name__=='__main__':raise SystemExit(main())
