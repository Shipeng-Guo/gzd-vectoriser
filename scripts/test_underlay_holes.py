import unittest
import numpy as np
from propose_underlay_holes import inventory

class HoleTests(unittest.TestCase):
    def test_complete_body_has_no_hole(self):
        a=np.zeros((40,50),dtype='uint8');a[5:35,5:45]=255
        self.assertEqual(inventory(a),[])
    def test_all_enclosed_holes_retained(self):
        a=np.full((40,50),255,dtype='uint8');a[10:12,20:24]=0;a[30,40]=0
        rows=inventory(a)
        self.assertEqual([r['pixels'] for r in rows],[8,1])
        self.assertEqual(rows[0]['box_xyxy'],[20,10,24,12])
    def test_border_opening_is_not_enclosed(self):
        a=np.full((40,50),255,dtype='uint8');a[0:20,15:20]=0
        self.assertEqual(inventory(a),[])
    def test_translucency_is_explicit_threshold(self):
        a=np.full((40,50),255,dtype='uint8');a[10:12,20:24]=240
        self.assertEqual(len(inventory(a,250)),1)
        self.assertEqual(inventory(a,200),[])

if __name__=='__main__':
    unittest.main()
