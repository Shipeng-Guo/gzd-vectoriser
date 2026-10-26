import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image
from exact_difference import measure, export, white

class ExactTests(unittest.TestCase):
 def a(self,h=97,w=129):return np.full((h,w,4),255,np.uint8)
 def test_identical_and_dimensions(self):
  a=self.a();r=measure(a,a);self.assertEqual(r['proof']['normalized_changed_pixels'],0)
  self.assertEqual(r['tiles'],[])
  with self.assertRaises(ValueError):measure(a,a[:-1])
 def test_one_level_one_pixel_and_all_grid_edges(self):
  a=self.a();b=a.copy()
  for y,x in [(0,0),(96,128),(95,95),(96,96)]:b[y,x,1]=254
  r=measure(a,b,96);self.assertEqual(r['proof']['normalized_changed_pixels'],4)
  self.assertEqual(r['proof']['unassigned_changed_pixels'],0)
  self.assertEqual(int(r['rgba_delta'].sum()),4)
 def test_hue_alpha_and_white_composite(self):
  a=self.a();b=a.copy();a[5,5,:3]=(100,200,100);b[5,5,:3]=(200,100,100)
  a[10,10]=[255,255,255,0];b[10,10]=[255,255,255,1]
  r=measure(a,b);self.assertEqual(r['proof']['normalized_changed_pixels'],2)
  self.assertEqual(r['proof']['white_composite_changed_pixels'],1)
 def test_many_disconnected_differences_no_budget(self):
  a=self.a(512,512);b=a.copy();b[::7,::7,0]=254
  r=measure(a,b,16)
  self.assertEqual(r['proof']['normalized_changed_pixels'],74*74)
  self.assertEqual(len(r['tiles']),1024)
  self.assertEqual(sum(t['changed_pixels'] for t in r['tiles']),74*74)
 def test_sweep_temporal_derivative_equals_difference(self):
  rng=np.random.default_rng(51);a=rng.integers(0,256,(7,13,4),dtype=np.uint8);b=rng.integers(0,256,a.shape,dtype=np.uint8)
  # Move a hard divider one column each step. Every coordinate switches exactly once.
  last=b.copy();acc=np.zeros(a.shape,dtype=np.int16)
  for x in range(1,14):
   frame=b.copy();frame[:,:x]=a[:,:x]
   acc+=abs(frame.astype(np.int16)-last.astype(np.int16));last=frame
  np.testing.assert_array_equal(acc,measure(a,b)['rgba_delta'])
 def test_normalization_and_iteration(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);a=self.a();b=a.copy();b[1,1,0]=240;b[80,100,2]=120
   Image.fromarray(a).save(p/'a.png');Image.fromarray(b).save(p/'b.png')
   m=export(p/'a.png',p/'b.png',p/'scan1',32)
   b[1,1]=a[1,1];b[20,40,0]=200;Image.fromarray(b).save(p/'c.png')
   n=export(p/'a.png',p/'c.png',p/'scan2',32,p/'scan1/manifest.json')
   counts=n['transition']['pixel_counts']
   self.assertEqual(counts,{'new_difference':1,'resolved_to_equal':1,'remaining_difference':1,'candidate_changed':2})
   self.assertEqual(n['transition']['reopen_tile_ids'],['exact_t32_x00000_y00000','exact_t32_x00032_y00000'])
   self.assertTrue((p/'scan2/index.html').exists())
   # Corrupted prior evidence must not be reused as a trustworthy comparison baseline.
   (p/'scan1/mask.png').write_bytes(b'invalid')
   with self.assertRaises(ValueError):export(p/'a.png',p/'c.png',p/'scan3',32,p/'scan1/manifest.json')
 def test_output_cannot_overwrite_input(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);a=self.a();Image.fromarray(a).save(p/'source.png')
   before=(p/'source.png').read_bytes()
   with self.assertRaises(ValueError):export(p/'source.png',p/'source.png',p)
   self.assertEqual((p/'source.png').read_bytes(),before)
 def test_random_assignment_all_changed_pixels(self):
  rng=np.random.default_rng(99)
  for h,w in [(1,1),(19,99),(193,222)]:
   a=rng.integers(0,256,(h,w,4),dtype=np.uint8);b=a.copy()
   mask=rng.random((h,w))<.43;b[mask,0]^=1
   r=measure(a,b,24);self.assertEqual(r['proof']['assigned_changed_pixels'],int(mask.sum()))
   self.assertEqual(r['proof']['unassigned_changed_pixels'],0)

if __name__=='__main__':unittest.main(verbosity=2)
