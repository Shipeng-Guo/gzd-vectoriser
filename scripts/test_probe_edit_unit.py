"""Generated geometry regression: wrong ownership must fail, including under transforms."""
import argparse,json,subprocess,tempfile
from pathlib import Path

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--node',default='node');ap.add_argument('--browser',required=True);a=ap.parse_args()
 script=Path(__file__).with_name('probe_edit_unit.mjs')
 with tempfile.TemporaryDirectory() as tmp:
  p=Path(tmp);cases=p/'cases.json';cases.write_text(json.dumps([{'id':'object','delta':[9,4],'watch':['external']}]))
  target='<g id="object"><circle cx="35" cy="50" r="10" fill="#bcb0de"/><text x="31" y="53" font-size="8">A</text>{inside}</g>'
  arrow='<path id="external" d="M 18 21 L 36 37" stroke="black" fill="none"/>'
  for name,wrong,trans in [('wrong',True,''),('correct',False,''),('transformed',False,'transform="translate(8 4) scale(1.3)"'),('sharp-wrong',True,''),('sharp-correct',False,''),('nested-correct',False,''),('nested-wrong',True,'')]:
   svg=p/(name+'.svg');nested_open='<svg x="10" y="8" width="140" height="100" viewBox="0 0 140 100">' if name.startswith('nested-') else '';nested_close='</svg>' if nested_open else '';svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="120" viewBox="0 0 160 120"><rect width="160" height="120" fill="white"/>'+nested_open+'<g '+trans+'>'+target.format(inside=arrow if wrong else '')+('' if wrong else arrow)+'</g>'+nested_close+'</svg>')
   out=p/name;run=subprocess.run([a.node,str(script),str(svg),'--cases',str(cases),'--out',str(out),'--browser',a.browser]+(['--pixel-renderer','sharp'] if name.startswith('sharp-') else []),capture_output=True,text=True)
   data=json.loads((out/'result.json').read_text());expected=not wrong
   assert data['pass']==expected,(name,run.returncode,run.stderr,data)
   assert run.returncode==(0 if expected else 2),(name,run)
   if wrong:assert not data['cases'][0]['watched'][0]['unchanged']
   if trans:assert all(abs(x-y)<.02 for x,y in zip(data['cases'][0]['actual_delta'],[11.7,5.2]))
   print(name,'expected',expected,'observed',data['pass'])
  # Required members must actually belong to the moving object, not merely exist.
  for name,inside,expected in [('member-inside',True,True),('member-outside',False,False),('member-missing',False,False)]:
   cases.write_text(json.dumps([{'id':'object','delta':[9,4],'watch':['external'],'members':['attached']}]))
   member='<circle id="attached" cx="45" cy="50" r="3" fill="red"/>'
   svg=p/(name+'.svg');svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="120" viewBox="0 0 160 120"><rect width="160" height="120" fill="white"/>'+target.format(inside=member if inside else '')+('' if inside or name=='member-missing' else member)+arrow+'</svg>')
   out=p/name;run=subprocess.run([a.node,str(script),str(svg),'--cases',str(cases),'--out',str(out),'--browser',a.browser,'--pixel-renderer','sharp'],capture_output=True,text=True)
   data=json.loads((out/'result.json').read_text());assert data['pass']==expected,(name,run.stderr,data)
   assert run.returncode==(0 if expected else 2)
   assert data['cases'][0]['watched'][0]['unchanged']
   assert data['cases'][0]['required_members_before'][0]['owned']==inside
   print(name,'expected',expected,'observed',data['pass'])
if __name__=='__main__':main()
