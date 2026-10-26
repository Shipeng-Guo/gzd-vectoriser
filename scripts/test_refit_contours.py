import unittest, tempfile, xml.etree.ElementTree as E
from pathlib import Path
import numpy as np, cv2
from refit_contours import *

def polygon(p):return 'M'+' L'.join(','.join(map(str,q)) for q in p)+' Z'
def boundary(mask):return cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)[0][0][:,0,:]
class FittingTests(unittest.TestCase):
 def test_staircase_circle(self):
  a=np.zeros((170,170),np.uint8);cv2.circle(a,(85,85),63,255,-1);d=polygon(boundary(a));new,m=refit_path(d)
  self.assertEqual(m['status'],'changed');self.assertLess(m['new_commands'],m['old_commands']/8)
  p=parse_closed(new)[0];rad=np.linalg.norm(p-[85,85],axis=1);self.assertLess(np.std(rad),.5);self.assertEqual(topology(parse_closed(d)),topology(parse_closed(new)))
 def test_sharp_square_corners(self):
  p=np.array([[20,20],[110,20],[110,100],[20,100]]);d=polygon(p);new,m=refit_path(d);self.assertEqual(m['status'],'changed')
  q=np.concatenate(parse_closed(new));self.assertTrue(all(np.min(np.linalg.norm(q-v,axis=1))<.8 for v in p));self.assertGreaterEqual(m['protected_corners'],4)
 def test_dumbbell_neck_and_hole(self):
  a=np.zeros((130,210),np.uint8);cv2.circle(a,(50,65),36,255,-1);cv2.circle(a,(158,65),36,255,-1);cv2.rectangle(a,(50,62),(158,68),255,-1)
  d=polygon(boundary(a));new,m=refit_path(d);self.assertEqual(m['status'],'changed');self.assertEqual(topology(parse_closed(d)),topology(parse_closed(new)));self.assertGreater(m['narrow_samples'],0)
  ring='M10 10L150 10L150 150L10 150Z M50 50L50 110L110 110L110 50Z';new,m=refit_path(ring);self.assertEqual(topology(parse_closed(ring)),topology(parse_closed(new)))
 def test_open_and_unsupported_rejected(self):
  with self.assertRaises(ValueError):parse_closed('M0 0 L2 2')
  with self.assertRaises(ValueError):parse_closed('M0 0 A1 1 0 0 0 2 2Z')
 def test_scope_and_no_overwrite(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'in.svg';o=Path(td)/'out.svg';p.write_text('<svg xmlns="http://www.w3.org/2000/svg"><g id="shape" data-method="local-source-contours-and-cubic-fit"><path id="shape.p1" d="M0 0L50 0L50 50L0 50Z"/></g><g id="arrow"><path d="M0 0L10 5L0 10Z"/></g></svg>')
   apply_svg(p,o,['shape']);self.assertEqual(E.parse(p).find('.//*[@id="arrow"]')[0].get('d'),E.parse(o).find('.//*[@id="arrow"]')[0].get('d'))
   with self.assertRaises(ValueError):apply_svg(p,o,['shape'])
   with self.assertRaises(ValueError):apply_svg(p,Path(td)/'bad.svg',['arrow'])
 def test_explicit_named_trace_and_manual_protection(self):
  with tempfile.TemporaryDirectory() as td:
   a=np.zeros((170,170),np.uint8);cv2.circle(a,(85,85),63,255,-1);d=polygon(boundary(a))
   p=Path(td)/'in.svg';o=Path(td)/'out.svg'
   p.write_text(f'<svg xmlns="http://www.w3.org/2000/svg"><g id="generic-network" data-method="source-traced"><path id="named-green-fibre" data-refit="true" d="{d}"/><path id="handmade" data-refit="true" data-manual="true" d="{d}"/><path id="unselected" d="{d}"/></g></svg>')
   report=apply_svg(p,o,['generic-network']);root=E.parse(o)
   self.assertNotEqual(root.find('.//*[@id="named-green-fibre"]').get('d'),d)
   self.assertEqual(root.find('.//*[@id="handmade"]').get('d'),d)
   self.assertEqual(root.find('.//*[@id="unselected"]').get('d'),d)
   self.assertEqual(report['groups']['generic-network']['counts']['changed'],1)
if __name__=='__main__':unittest.main()
