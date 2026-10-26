"""Synthetic negative/positive occlusion and stale-evidence regressions."""
import argparse,json,tempfile,subprocess,hashlib,sys,unittest
from pathlib import Path
import acceptance_probes as gate
p=argparse.ArgumentParser();p.add_argument('--node',required=True);p.add_argument('--browser',required=True);args,rest=p.parse_known_args();ROOT=Path(__file__).parent
class Tests(unittest.TestCase):
 def test_real_opening_preserved_and_overfill_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);svg=d/'drawing.svg';cp=d/'contract.json'
   contract={'version':1,'cases':[{'id':'pocket','foreground':['front'],'underlay':['base'],'reason':'Independent source expectation: solid wall and genuinely open pocket','solid_regions':[{'id':'wall','polygon':[[15,30],[20,30],[20,40],[15,40]]}],'clear_regions':[{'id':'opening','polygon':[[44,44],[52,44],[52,52],[44,52]],'max_alpha':5}]}]}
   cp.write_text(json.dumps(contract))
   for filled in (False,True):
    hole='' if filled else 'M35 35V65H65V35Z'
    svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path id="base" d="M10 10H90V90H10Z {hole}" fill="green" fill-rule="evenodd"/><rect id="front" x="38" y="38" width="25" height="25" fill="red"/></svg>')
    out=d/str(filled);run=subprocess.run([args.node,str(ROOT/'probe_occlusion.mjs'),str(svg),'--contract',str(cp),'--out',str(out),'--browser',args.browser],capture_output=True,text=True)
    self.assertEqual(run.returncode,2 if filled else 0,run.stderr)
    result=out/'result.json';data=json.loads(result.read_text());self.assertEqual(data['pass'],not filled)
    j={'artifact':str(svg),'artifact_sha256':gate.sha(svg),'discovery':{'state':'required'}};gate.register(j,cp);gate.attach(j,result)
    if filled:
     with self.assertRaisesRegex(ValueError,'failed'):gate.check(j)
    else:gate.check(j)
    data['cases'][0]['tests']=[x for x in data['cases'][0]['tests']if x['kind']!='clear'];bad=d/'omitted.json';bad.write_text(json.dumps(data))
    with self.assertRaisesRegex(ValueError,'omitted'):gate.attach(j,bad)
 def test_render_direction_hole_and_gate(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);svg=d/'drawing.svg';cp=d/'contract.json'
   c={'version':1,'cases':[{'id':'bridge','foreground':['front'],'underlay':['base'],'reason':'Confirmed solid rectangle is obscured by independent foreground stripe','solid_regions':[{'id':'core','polygon':[[40,30],[60,30],[60,70],[40,70]]}]}]};cp.write_text(json.dumps(c))
   def render(fill,name):
    svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><path id="base" d="{fill}" fill="orange"/><rect id="front" x="45" y="10" width="10" height="80" fill="purple"/></svg>')
    r=subprocess.run([args.node,str(ROOT/'probe_occlusion.mjs'),str(svg),'--contract',str(cp),'--out',str(d/name),'--browser',args.browser],capture_output=True,text=True)
    if r.returncode not in (0,2):self.fail(r.stderr)
    return d/name/'result.json'
   bad=render('M10 10H45V90H10Z M55 10H90V90H55Z','bad');self.assertFalse(json.loads(bad.read_text())['pass'])
   j={'artifact':str(svg),'artifact_sha256':gate.sha(svg),'discovery':{'state':'passed'}};gate.register(j,cp);gate.attach(j,bad)
   with self.assertRaisesRegex(ValueError,'failed'):gate.check(j)
   # A full, independently authored bottom body passes the same frozen witnesses.
   good=render('M10 10H90V90H10Z','good');j['artifact_sha256']=gate.sha(svg);gate.attach(j,good);gate.check(j)
   svg.write_text(svg.read_text().replace('orange','red'));j['artifact_sha256']=gate.sha(svg)
   with self.assertRaisesRegex(ValueError,'stale'):gate.check(j)
   wrong=json.loads(good.read_text());wrong['artifact_sha256']=j['artifact_sha256'];wrong['cases'][0]['foreground']=['base'];w=d/'wrong.json';w.write_text(json.dumps(wrong))
   with self.assertRaisesRegex(ValueError,'direction'):gate.attach(j,w)
   # Omitting a declared check or mutating the contract cannot produce acceptance.
   wrong['cases']=[];w.write_text(json.dumps(wrong))
   with self.assertRaisesRegex(ValueError,'omitted'):gate.attach(j,w)
   cp.write_text(json.dumps({'version':1,'cases':[]}))
   with self.assertRaisesRegex(ValueError,'changed'):gate.check(j)
if __name__=='__main__':unittest.main(argv=[sys.argv[0]]+rest)
