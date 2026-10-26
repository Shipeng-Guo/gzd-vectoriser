import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
from PIL import Image
from review_loop import validate_exact_inventory

SCRIPTS=Path(__file__).parent
class IntegrationTests(unittest.TestCase):
 def call(self,*args,ok=True):
  r=subprocess.run([sys.executable,*map(str,args)],capture_output=True,text=True)
  self.assertEqual(r.returncode==0,ok,r.stdout+r.stderr);return r
 def test_report_bundles_full_inventory_and_refuses_bad_evidence(self):
  from exact_difference import export,sha
  from build_report import copy_exact_viewer
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);a=np.full((12,17,4),255,np.uint8);b=a.copy();b[3,4,0]=254
   Image.fromarray(a).save(p/'a.png');Image.fromarray(b).save(p/'b.png')
   m=export(p/'a.png',p/'b.png',p/'scan')
   s={'version':4,'reference_sha256':sha(p/'a.png'),'candidate_sha256':sha(p/'b.png'),'canvas':[17,12],
      'exact':{'manifest':str(p/'scan/manifest.json'),'manifest_sha256':sha(p/'scan/manifest.json')},'exhaustive_regions':m['tiles']}
   (p/'report').mkdir();link=copy_exact_viewer(s,p/'report')
   self.assertTrue((p/'report'/link).exists())
   for f in m['files'].values():self.assertEqual(sha(p/'report/exact'/f['path']),f['sha256'])
   self.assertNotIn('__SCAN_DATA__',(p/'report'/link).read_text())
   (p/'scan/mask.png').write_bytes(b'corrupted')
   (p/'badreport').mkdir()
   with self.assertRaises(ValueError):copy_exact_viewer(s,p/'badreport')
 def test_all_tiles_mandatory_and_changed_tiles_reopen(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);a=np.full((64,64,4),255,np.uint8);b=a.copy();b[5,5,:3]=0;b[40,40,:3]=0;b[5,40,:3]=0
   Image.fromarray(a).save(p/'a.png');Image.fromarray(b).save(p/'b.png')
   def scan(name,extra=()):
    self.call(SCRIPTS/'scan_differences.py','--reference',p/'a.png','--candidate',p/'b.png','--out',p/name,'--per-channel','1','--tile-size','64','--exact-tile-size','32','--lean',*extra)
    return p/name/'scan.json'
   def loop(action,*extra,ok=True):
    return self.call(SCRIPTS/'review_loop.py',action,'--ledger',p/'review.json',*extra,ok=ok)
   first=scan('first');s=json.loads(first.read_text());self.assertEqual(len(s['exhaustive_regions']),3)
   bad=copy.deepcopy(s);bad['exhaustive_regions'].pop()
   with self.assertRaisesRegex(ValueError,'omitted'):validate_exact_inventory(bad)
   loop('init','--scan',first)
   for i in json.loads((p/'review.json').read_text())['items']:
    loop('begin','--id',i['id']);loop('record','--id',i['id'],'--verdict','pass','--note','Synthetic bookkeeping fixture; this is not a real-image quality approval.','--evidence',i['evidence'])
   loop('export-regions','--scan',first,'--output',p/'regions.json')
   b[5,5,:3]=[20,20,20];b[41,41,3]=128;Image.fromarray(b).save(p/'b.png')
   second=scan('second',('--regions',p/'regions.json','--previous-exact',p/'first/exact/manifest.json'))
   loop('rebase','--scan',second)
   j=json.loads((p/'review.json').read_text());exact={i['id']:i for i in j['items'] if i['channel']=='exact_difference'}
   self.assertEqual(exact['exact_t32_x00000_y00000']['state'],'open')
   self.assertEqual(exact['exact_t32_x00032_y00032']['state'],'open')
   self.assertEqual(exact['exact_t32_x00032_y00000']['state'],'pass')
   self.assertEqual(json.loads((p/'second/exact/manifest.json').read_text())['transition']['reopen_tile_ids'],['exact_t32_x00000_y00000','exact_t32_x00032_y00032'])
   loop('check','--scan',second,ok=False)
   for i in j['items']:
    if i['state']=='open':
     loop('begin','--id',i['id']);loop('record','--id',i['id'],'--verdict','pass','--note','Synthetic changed tile fixture observed after revision.','--evidence',i['evidence'])
   loop('export-regions','--scan',second,'--output',p/'regions2.json')
   loop('start-discovery','--scan',second)
   third=scan('third',('--regions',p/'regions2.json'))
   loop('rebase','--scan',third)
   j=json.loads((p/'review.json').read_text())
   self.assertTrue(all(i['state']=='open' for i in j['items'] if i['channel']=='exact_difference'))
   loop('finish-discovery','--scan',third,'--note','Cannot finish while tiles remain unreviewed.',ok=False)

if __name__=='__main__':unittest.main(verbosity=2)
