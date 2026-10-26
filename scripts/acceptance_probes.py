"""Bound, independently declared occlusion requirements. No semantic auto-pass."""
from pathlib import Path
import hashlib,json,time

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def register(j,contract):
 p=Path(contract).resolve();c=read(p)
 ids=[x['id'] for x in c.get('cases',[])]
 if c.get('version')!=1 or not ids or len(ids)!=len(set(ids)):raise ValueError('Nonempty distinct occlusion cases required')
 for x in c['cases']:
  if not all(x.get(k) for k in ('foreground','underlay','solid_regions','reason')):raise ValueError('Occlusion case lacks direction or solid witnesses')
 old=j.get('acceptance_probes')
 if old and old['contract_sha256']!=sha(p):raise ValueError('Do not replace registered obligations to bypass a failure; preserve contract, use a separate explicitly reviewed revision.')
 j['acceptance_probes']=old or {'contract':str(p),'contract_sha256':sha(p),'required_cases':ids,'history':[],'latest':None}
 j['discovery']['state']='required'

def attach(j,result):
 a=j.get('acceptance_probes')
 if not a:raise ValueError('Register the contract before importing any result')
 p=Path(result).resolve();r=read(p)
 if r.get('contract_sha256')!=a['contract_sha256'] or sha(a['contract'])!=a['contract_sha256']:raise ValueError('Probe contract mismatch')
 if r.get('artifact_sha256')!=j.get('artifact_sha256') or sha(j['artifact'])!=j['artifact_sha256']:raise ValueError('Probe result is for a different artifact; rebase then rerun')
 ids=[x['id'] for x in r.get('cases',[])]
 if sorted(ids)!=sorted(a['required_cases']) or len(ids)!=len(set(ids)):raise ValueError('Probe omitted/duplicated required cases')
 expected=read(a['contract'])
 for c in r['cases']:
  src=next(x for x in expected['cases'] if x['id']==c['id'])
  if c.get('foreground')!=src['foreground'] or c.get('underlay')!=src['underlay']:raise ValueError('Probe reversed or changed occlusion direction')
  if sorted(x['id'] for x in c.get('tests',[]))!=sorted(x['id'] for x in src['solid_regions']+src.get('clear_regions',[])):raise ValueError('Probe omitted solid/opening witnesses')
  for witness in src.get('clear_regions',[]):
   if next(x for x in c['tests'] if x['id']==witness['id']).get('kind')!='clear':raise ValueError('Probe changed opening witness type')
  if not c['tests'] or any(x.get('sampled_pixels',0)<=0 for x in c['tests']):raise ValueError('Empty witness evidence')
  ok=all(x.get('failed_pixels')==0 and x.get('pass') is True for x in c['tests'])
  if c.get('pass')!=ok:raise ValueError('Inconsistent case verdict')
 if r.get('pass')!=all(c['pass'] for c in r['cases']):raise ValueError('Inconsistent overall verdict')
 if not r.get('evidence'):raise ValueError('No probe render evidence')
 for e in r['evidence']:
  if sha(e['path'])!=e['sha256']:raise ValueError('Probe evidence changed')
 entry={'path':str(p),'sha256':sha(p),'artifact_sha256':r['artifact_sha256'],'pass':r['pass'],'recorded_at_ns':time.time_ns()}
 a['latest']=entry;a['history'].append(entry);j['discovery']['state']='required'

def check(j):
 a=j.get('acceptance_probes')
 if not a:return
 if sha(a['contract'])!=a['contract_sha256']:raise ValueError('Registered probe contract changed')
 e=a.get('latest')
 if not e:raise ValueError('Registered occlusion probes have not run')
 if not e['pass']:raise ValueError('Occlusion probe failed; hidden underlay is unresolved')
 if e['artifact_sha256']!=j['artifact_sha256']:raise ValueError('Occlusion evidence stale after SVG change')
 if sha(e['path'])!=e['sha256']:raise ValueError('Probe result changed')
 r=read(e['path'])
 for im in r['evidence']:
  if sha(im['path'])!=im['sha256']:raise ValueError('Probe image changed')
