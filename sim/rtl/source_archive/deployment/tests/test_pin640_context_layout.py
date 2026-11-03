"""Hand checked tree mapping, lane tails and geometry assumptions."""
import bisect
import struct
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import z100_pin640_context_layout as layout


class ContextLayoutTests(unittest.TestCase):
    def test_tree_map_bijection(self):
        indices=[]
        for level in range(8):
            for path in range(1<<level):
                index=layout.original_index(level,path)
                self.assertEqual(layout.node_address(index),(level,path))
                indices.append(index)
        self.assertEqual(sorted(indices),list(range(255)))
        self.assertEqual(layout.node_address(127),(0,0))
        self.assertEqual(layout.node_address(254),(7,127))

    def test_interleaved_lane_context_offsets_and_tail(self):
        tables=[tuple([-100+channel]*254) for channel in range(33)]
        data=layout.pack_layer(tables)
        def key(lane,context,index):
            level,path=layout.node_address(index)
            return struct.unpack_from('<q',data,layout.bank_offset(level,lane,context,path))[0]
        self.assertEqual(key(31,0,127),-69)
        self.assertEqual(key(0,1,0),-68)
        self.assertEqual(key(1,1,0),layout.SENTINEL)
        self.assertEqual(key(0,0,254),layout.SENTINEL)
        self.assertEqual(len(data),32*8*255*8)

    def test_signed_edges_duplicates_and_sentinel_search(self):
        for table in ([layout.MINIMUM]*254,[layout.SENTINEL]*254,[-1]*127+[1]*127):
            data=layout.pack_layer([table])
            for raw in (layout.MINIMUM,-2,-1,0,1,layout.SENTINEL-1):
                path=0
                for level in range(8):
                    offset=layout.bank_offset(level,0,0,path)
                    key=struct.unpack_from('<q',data,offset)[0]
                    path=path*2+(raw>=key)
                self.assertEqual(path-127,bisect.bisect_right(table,raw)-127)

    def test_fixed_geometry_is_not_full_platform_acceptance(self):
        result=layout.geometry()
        self.assertEqual([r['depth'] for r in result['levels']],[8,16,32,64,128,256,512,1024])
        self.assertEqual(result['lane_ramb18_equivalent'],9)
        self.assertEqual(result['lanes32_bram36_equivalent'],144)
        self.assertFalse(result['includes_weight_window_activation_cache'])
        self.assertFalse(result['frequency_accepted'])

    def test_reject_invalid_indices_and_capacity(self):
        for index in (-1,255,True):
            with self.assertRaises(ValueError):layout.node_address(index)
        with self.assertRaises(ValueError):layout.pack_layer([tuple([0]*254)]*257)
        with self.assertRaises(ValueError):layout.pack_layer([[1,0]+[0]*252])
        with self.assertRaises(ValueError):layout.pack_layer([[layout.SENTINEL+1]*254])


if __name__=='__main__':unittest.main()
