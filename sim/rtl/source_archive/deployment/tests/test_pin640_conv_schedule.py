"""Hand calculations for loop ordering and table lifetime, independent of RTL."""
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import z100_pin640_conv_schedule as schedule


def toy(cout=33):
    node=dict(id=1,op='conv',inputs=[-1],shape=[1,cout,2,9],
              params=dict(groups=1,stride=[1,1],dilation=[1,1],padding=[0,0]))
    groups=(cout+31)//32
    window=dict(node_id=1,output_channel_groups=groups,issues=groups*4,
                unique_word_reads=groups*8,conflict_issues=0,physical_mapping=dict(bank_count=32))
    return schedule.analyze_conv_layer(node,[1,4,2,9],(cout,4,1,1),cout*4,cout*4,window)


class ConvScheduleTests(unittest.TestCase):
    def test_tail_and_row_restart_count(self):
        row=toy()
        self.assertEqual(row['output_group_valid_channels'],[32,1])
        self.assertEqual(row['horizontal_tiles_per_row'],2)
        self.assertEqual(row['spatial_tiles'],4)
        self.assertEqual(row['tilegroups'],8)
        self.assertEqual(row['row_aware_issue_count'],8)
        self.assertEqual(row['logical_macs'],2*9*33*4)
        self.assertEqual(row['output_beats'],64)
        self.assertEqual(row['ideal_overlap_compute_output_slots'],64)
        self.assertEqual(row['serial_mac_plus_output_beat_slots'],72)

    def test_group_reload_is_once_per_spatial_tile(self):
        row=toy()
        self.assertEqual(row['weight_reload_actual_row_site_total_bytes'],264*4)
        self.assertEqual(row['weight_reload_padded_row_site_total_bytes'],512*4)
        self.assertEqual(row['activation_scan_bytes_group_outer'],72*2)
        self.assertEqual(row['activation_scan_bytes_row_site_outer_lower_bound'],72)
        self.assertEqual(row['requant_payload_bits_row_site_outer_valid'],33*255*33*4)
        self.assertEqual(row['window_unique_word_reads_all_groups'],16)
        self.assertEqual(row['full_operand_tile_bytes_if_additional_cross_group_staging'],32)

    def test_single_group_context_remains_current(self):
        row=toy(1)
        self.assertEqual(row['requant_config_epochs_row_site_outer_reload_per_tilegroup'],1)
        self.assertEqual(row['weight_reload_actual_row_site_total_bytes'],8)
        self.assertEqual(row['requant_payload_bits_row_site_outer_valid'],255*33)
        self.assertEqual(row['requant_config_epochs_group_outer'],1)

    def test_config_ports_and_no_double_latency(self):
        cfg=schedule.requant_config_cycles()
        self.assertEqual(cfg['parallel_lanes_one_write_per_cycle'],257)
        self.assertEqual(cfg['shared_scalar_write_begin_commit_broadcast'],8162)
        self.assertEqual(cfg['shared_scalar_all_controls_per_lane'],8224)
        totals=schedule.aggregate_layers([toy()])
        self.assertEqual(totals['requant_parallel_config_cycles_group_outer'],514)
        self.assertEqual(totals['requant_parallel_config_cycles_row_site_outer_reload_per_tilegroup'],2056)
        self.assertEqual(totals['group_outer_serial_with_parallel_config_slots'],72+2*8+514)
        self.assertEqual(totals['row_site_reload_serial_with_parallel_config_slots'],72+8*8+2056)

    def test_aggregation_weights_layers_individually(self):
        a,b=toy(),toy(1)
        total=schedule.aggregate_layers([a,b])
        self.assertEqual(total['weight_bias_actual_row_site_total_bytes'],264*4+8)
        self.assertEqual(total['requant_config_epochs_row_site_outer_reload_per_tilegroup'],9)
        self.assertEqual(total['weight_bias_padded_model_once_bytes'],512+256)

    def test_rejects_missing_or_conflicting_window_evidence(self):
        node=dict(id=1,op='conv',inputs=[-1],shape=[1,33,2,9],
                  params=dict(groups=1,stride=1,dilation=1,padding=0))
        window=dict(node_id=1,output_channel_groups=2,issues=8,
                    unique_word_reads=16,conflict_issues=1,physical_mapping=dict(bank_count=32))
        with self.assertRaisesRegex(ValueError,'conflicts'):
            schedule.analyze_conv_layer(node,[1,4,2,9],(33,4,1,1),132,132,window)

    def test_frozen_full_graph_rebuild_is_bounded(self):
        value=schedule.build_report()
        self.assertEqual(value['status'],'CONTRACT_ONLY_FULL_SCHEDULE_UNIMPLEMENTED')
        self.assertEqual(len(value['layers']),63)
        self.assertEqual(value['totals']['row_aware_issue_count'],4753600)
        self.assertEqual(value['totals']['logical_macs'],4323744000)
        self.assertFalse(value['scope']['whole_frame_schedule_implemented'])
        self.assertFalse(value['scope']['fps_claim'])
        row=value['scenarios']['row_site_outer_group_then_tap']
        self.assertEqual(row['requant_threshold_payload_valid_bits_reload_per_tilegroup'],
                         sum(x['requant_payload_bits_row_site_outer_valid'] for x in value['layers']))
        self.assertEqual(row['window_local_word_reads'],value['totals']['window_unique_word_reads_all_groups'])


if __name__=='__main__':
    unittest.main()
