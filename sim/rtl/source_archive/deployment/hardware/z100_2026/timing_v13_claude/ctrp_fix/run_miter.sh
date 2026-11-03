#!/bin/sh
# Run the v13 vs v13p transaction miter. Needs iverilog 11 unpacked at $IV.
#   IV=/tmp/pkg/usr            (from: apt-get download iverilog; dpkg-deb -x ... /tmp/pkg)
# Usage: ./run_miter.sh <seed> <cycles> <pulse_mode 0|1>
set -e
IV=${IV:-/tmp/pkg/usr}
HERE=$(cd "$(dirname "$0")" && pwd)
SEED=${1:-1}; CYCLES=${2:-10000}; PULSE=${3:-0}
WORK=$(mktemp -d); cd "$WORK"
export LD_LIBRARY_PATH="$IV/lib/x86_64-linux-gnu"
"$IV/bin/iverilog" -B"$IV/lib/x86_64-linux-gnu/ivl" -g2012 -o tb.vvp -s tb_fbank_v13_vs_v13p \
  -P tb_fbank_v13_vs_v13p.SEED=$SEED -P tb_fbank_v13_vs_v13p.CYCLES=$CYCLES \
  -P tb_fbank_v13_vs_v13p.PULSE_MODE=$PULSE \
  "$HERE/tb/tb_fbank_v13_vs_v13p.sv" "$HERE/experimental/z100_feature_banks_writepipe_4k_v13p.sv" \
  "$HERE/rtl_ref/z100_feature_banks_writepipe_4k_v13.sv" \
  "$HERE/rtl_ref/z100_feature_banks_4read_writepipe_4k_v13.sv" \
  "$HERE/experimental/z100_feature_banks_4read_writepipe_4k_v13p.sv"
"$IV/bin/vvp" -M"$IV/lib/x86_64-linux-gnu/ivl" tb.vvp | tail -2
python3 "$HERE/tb/cmp_fbank_logs.py" ref.log new.log 1
