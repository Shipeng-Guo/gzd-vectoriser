#!/usr/bin/env python3
"""Persistent review loop and fail-closed completeness check, not a semantic correctness oracle.
No project paths. Standard library. Reviewer supplies actual observations and evidence.
"""
from pathlib import Path
import argparse,json,hashlib,time,re,os,tempfile,copy
import acceptance_probes
import independent_review
DONE={'pass','allowed_difference'}
VERDICTS=DONE|{'fix_required','uncertain'}
GENERIC_NOTES={'pass','passed','ok','okay','looks good','all good','no issues','no differences','matches source','same as source','reviewed','done','observed current canonical region','\u901a\u8fc7','\u5df2\u68c0\u67e5','\u5df2\u67e5\u770b','\u6b63\u5e38','\u65e0\u5dee\u5f02','\u4e00\u81f4','\u4e0e\u539f\u56fe\u4e00\u81f4'}
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,j):
 # A failed batch never publishes an intermediate ledger, including on write failure.
 p=Path(p);tmp=None
 try:
  with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=p.parent,prefix='.'+p.name+'.',suffix='.tmp',delete=False) as f:
   tmp=Path(f.name);json.dump(j,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if tmp and tmp.exists():tmp.unlink()
def items(s):return s['proposals']+s['coverage']+s.get('source_regions',[])+s.get('exhaustive_regions',[])
def in_box(a,b):return a[0]>=b[0] and a[1]>=b[1] and a[2]<=b[2] and a[3]<=b[3]
def overlap(a,b):return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])
def policy_ok(policy,issue):
 if not policy.get('reason') or not policy.get('allowed_changes') or not policy.get('invariants'):return False
 return in_box(issue['box_xyxy'],policy['box_xyxy']) and not any(overlap(issue['box_xyxy'],b) for b in policy.get('strict_boxes',[]))
def bind_evidence(item):
 # Bind the canonical scanner pair when imported, not an arbitrary later attachment.
 requirements(item)
 h=sha(item['evidence'])
 if item.get('scan_evidence_sha256',h)!=h:raise ValueError('Scanner evidence changed before import: '+item['id'])
 return dict(item,scan_evidence_sha256=h)
def requirements(item):
 req=item.get('requirements',{})
 if not isinstance(req,dict) or any(not isinstance(k,str) or not k.strip() or not isinstance(v,str) or not v.strip() for k,v in req.items()):raise ValueError('requirements must contain named, nonempty source expectations: '+item['id'])
 return req
def normalized_note(note):return re.sub(r'\s+',' ',note.strip().casefold()).strip(' .。!！')
def validate_note(note,strict=False):
 if not isinstance(note,str) or not note.strip():raise ValueError('A concrete observation note is required')
 if strict and normalized_note(note) in GENERIC_NOTES:raise ValueError('Use a region-specific observation, not a generic pass note')
def validate_checks(item,checks,verdict):
 req=requirements(item)
 if checks is None:
  if req and verdict in DONE:raise ValueError('Completion requires checks for every requirement: '+', '.join(req))
  return
 if not isinstance(checks,dict):raise ValueError('checks must be an object keyed by requirement name')
 unknown=set(checks)-set(req)
 if unknown:raise ValueError('Unknown requirement checks: '+', '.join(sorted(unknown)))
 for key,check in checks.items():
  if not isinstance(check,dict) or set(check)!={'verdict','note'} or check.get('verdict') not in {'pass','uncertain','fail'}:raise ValueError('Each check needs verdict pass/uncertain/fail and note: '+key)
  validate_note(check['note'],strict=True)
 if verdict in DONE:
  missing=set(req)-set(checks)
  if missing:raise ValueError('Missing requirement checks: '+', '.join(sorted(missing)))
  failed=[k for k,c in checks.items() if c['verdict']!='pass']
  if failed:raise ValueError('Unresolved requirement checks block completion: '+', '.join(failed))
def assert_current_inputs(j):
 # New ledgers store paths; legacy ledgers acquire them at the next rebase.
 for key in ('reference','candidate','artifact'):
  if j.get(key) and j.get(key+'_sha256') and sha(j[key])!=j[key+'_sha256']:raise ValueError(key.capitalize()+' changed; run a new scan and rebase before recording')
def validate_exact_inventory(s):
 if s.get('version',0)>=4 and not s.get('exact'):raise ValueError('Current scanner requires an exact inventory')
 if not s.get('exact'):return
 e=s['exact'];p=Path(e['manifest'])
 if sha(p)!=e['manifest_sha256']:raise ValueError('Exact inventory manifest changed')
 m=read(p)
 if any(m[k]!=s[k] for k in ('reference_sha256','candidate_sha256','canvas')):raise ValueError('Exact inventory inputs do not match scan')
 if m['proof']['unassigned_changed_pixels']!=0 or m['proof']['assigned_changed_pixels']!=m['proof']['normalized_changed_pixels']:raise ValueError('Exact pixel assignment is incomplete')
 expected={t['id']:(t['box_xyxy'],t['changed_pixels']) for t in m['tiles']}
 got={t['id']:(t['box_xyxy'],t['changed_pixels']) for t in s.get('exhaustive_regions',[])}
 if got!=expected or len(got)!=len(s.get('exhaustive_regions',[])):raise ValueError('Exact review tiles were omitted, duplicated or changed')
 for f in m['files'].values():
  if sha(p.parent/f['path'])!=f['sha256']:raise ValueError('Exact pixel evidence missing or changed')
def assert_scan_inputs(s):
 validate_exact_inventory(s)
 for key in ('reference','candidate'):
  if sha(s[key])!=s[key+'_sha256']:raise ValueError(key.capitalize()+' changed after this scan')
def find_item(j,item_id):
 i=next((i for i in j['items'] if i['id']==item_id),None)
 if i is None:raise ValueError('Unknown issue ID: '+str(item_id))
 return i
def pending_ids(j):return [q['id'] for q in j['items'] if q.get('pending_fix') or q['state'] in {'fix_required','uncertain'}]
def begin_item(j,item_id,verify_inputs=True):
 i=find_item(j,item_id)
 if j.get('discovery',{}).get('state')=='awaiting_scan':raise ValueError('Run and import the requested fresh scan before reviewing.')
 if j['active'] not in [None,item_id]:raise ValueError('Finish active region first: '+j['active'])
 pending=pending_ids(j)
 if pending and item_id!=pending[0]:raise ValueError('Resolve the first pending issue before advancing: '+pending[0])
 if verify_inputs:assert_current_inputs(j)
 if j.get('discovery',{}).get('state')=='passed':j['discovery']['state']='required'
 j['active']=item_id;i['state']='reviewing'
 return i
def record_observation(j,row,strict_note=False,verify_inputs=True):
 i=find_item(j,row.get('id'))
 if j['active']!=i['id']:raise ValueError('Begin this region first')
 if row.get('verdict') not in VERDICTS:raise ValueError('An explicit valid verdict is required')
 validate_note(row.get('note'),strict=strict_note)
 if not isinstance(row.get('evidence'),(str,Path)) or not Path(row['evidence']).is_file():raise ValueError('Existing evidence is required')
 if verify_inputs:assert_current_inputs(j)
 evidence=Path(row['evidence']);verdict=row['verdict']
 canonical_hash=sha(i['evidence']);bound_hash=i.get('scan_evidence_sha256',canonical_hash)
 evidence_hash=canonical_hash if evidence.resolve()==Path(i['evidence']).resolve() else sha(evidence)
 if canonical_hash!=bound_hash:raise ValueError('Registered scan evidence changed; run a new scan and rebase.')
 if evidence_hash!=bound_hash:raise ValueError('Observation requires the current registered scan pair (or a byte-identical copy), not stale or unrelated evidence.')
 validate_checks(i,row.get('checks'),verdict)
 if verdict=='allowed_difference':
  p=next((p for p in j['policies'] if p['id']==row.get('policy_id')),None)
  if not p or not policy_ok(p,i):raise ValueError('Policy must explicitly cover this box and not overlap strict regions')
 if verdict in {'fix_required','uncertain'} and j.get('discovery',{}).get('state')=='reviewing':j['discovery']['found_problem']=True
 i['scan_evidence_sha256']=bound_hash
 observation={'verdict':verdict,'note':row['note'],'candidate_sha256':j['candidate_sha256'],'evidence':str(evidence.resolve()),'evidence_sha256':evidence_hash,'policy_id':row.get('policy_id'),'scan_evidence_sha256':bound_hash,'source_crop_sha256':i['source_crop_sha256'],'candidate_crop_sha256':i['candidate_crop_sha256'],'recorded_at_ns':time.time_ns()}
 if requirements(i):observation.update(requirements=copy.deepcopy(requirements(i)),checks=copy.deepcopy(row.get('checks',{})))
 i['state']=verdict;i['pending_fix']=verdict not in DONE;i['history'].append(observation);j['active']=None if verdict in DONE else i['id']
 if verdict not in DONE:independent_review.track_local(j,i,observation)
 return {'id':i['id'],'state':i['state']}
def record_batch(j,rows):
 if not isinstance(rows,list) or not rows:raise ValueError('observations must be a nonempty JSON array; no defaults are accepted')
 assert_current_inputs(j)
 work=copy.deepcopy(j);seen_ids=set();seen_notes={};results=[]
 for n,row in enumerate(rows):
  if not isinstance(row,dict) or not {'id','verdict','note','evidence'}<=set(row) or set(row)-{'id','verdict','note','evidence','checks','policy_id'}:raise ValueError('Each observation needs explicit id, verdict, note and evidence; optional checks and policy_id only')
  if not isinstance(row['id'],str) or row['id'] in seen_ids:raise ValueError('Batch IDs must be distinct explicit strings')
  validate_note(row['note'],strict=True);note=normalized_note(row['note'])
  if row['verdict'] in {'fix_required','uncertain'} and n!=len(rows)-1:raise ValueError('An unresolved observation must be last; finish its repair before advancing')
  begin_item(work,row['id'],verify_inputs=False);result=record_observation(work,row,strict_note=True,verify_inputs=False)
  # Different channel nominations may refer to one identical physical observation.
  # Compare validated evidence and decisions; never require cosmetic ID suffixes.
  item=find_item(work,row['id']);h=item['history'][-1]
  signature=(item['box_xyxy'],h['source_crop_sha256'],h['candidate_crop_sha256'],h['evidence_sha256'],h['scan_evidence_sha256'],requirements(item),row['verdict'],row.get('policy_id'),row.get('checks'))
  if note in seen_notes and seen_notes[note]!=signature:raise ValueError('Repeated batch notes require identical boxes, current hashes, requirements, verdict, policy and checks')
  seen_ids.add(row['id']);seen_notes[note]=copy.deepcopy(signature);results.append(result)
 assert_current_inputs(work)
 return work,results
def print_queue(j,action,limit):
 pending=pending_ids(j);active=j.get('active');waiting=[i for i in j['items'] if i['state'] not in DONE]
 first=active or (pending[0] if pending else None)
 if first:waiting.sort(key=lambda i:i['id']!=first)
 summary={'active':active,'pending':pending,'discovery':j.get('discovery',{}).get('state','required'),'remaining':len(waiting),'total':len(j['items'])}
 if action=='queue':summary['items']=[{k:i[k] for k in ('id','state','box_xyxy','evidence','scan_evidence_sha256','requirements') if k in i} for i in waiting[:limit]]
 elif waiting:summary['next']={k:waiting[0][k] for k in ('id','state','evidence','requirements') if k in waiting[0]}
 print(json.dumps(summary,ensure_ascii=False))
def export_regions(j,args):
 if not args.output:raise ValueError('export-regions requires --output.')
 if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*',args.prefix):raise ValueError('Prefix must be a nonempty safe identifier prefix.')
 s=read(args.scan) if args.scan else None
 if s and s['reference_sha256']!=j['reference_sha256']:raise ValueError('Reference changed; cannot export these fixed boxes for this scan.')
 canvas=j.get('canvas') or (s.get('canvas') if s else None)
 if not canvas or len(canvas)!=2 or not all(isinstance(v,int) and v>0 for v in canvas):raise ValueError('Canvas is unavailable; supply --scan with its canvas for this legacy ledger.')
 protected=[args.ledger,args.scan,args.artifact]+([Path(s[k]) for k in ('reference','candidate') if k in s] if s else [])
 if args.output.resolve() in {p.resolve() for p in protected if p}:raise ValueError('Output must not overwrite the ledger, scan or reviewed inputs.')
 rows=[]
 for n,i in enumerate(j['items'],1):
  box=i['box_xyxy']
  if len(box)!=4 or not (0<=box[0]<box[2]<=canvas[0] and 0<=box[1]<box[3]<=canvas[1]):raise ValueError('Fixed box is outside the canvas: '+i['id'])
  safe_id=re.sub(r'[^A-Za-z0-9_.-]','_',i['id'])
  row={'id':f'{args.prefix}{n:04d}_{safe_id}','ledger_id':i['id'],'name':i.get('name',i['id']),'box_xyxy':box}
  if requirements(i):row['requirements']=copy.deepcopy(requirements(i))
  rows.append(row)
 save(args.output,{'canvas':canvas,'regions':rows});print(json.dumps({'regions':len(rows),'output':str(args.output)}))
def assert_local_complete(j,s,artifact):
 acceptance_probes.check(j)
 assert_scan_inputs(s)
 # Every current exact tile must be represented even if a ledger is otherwise all-pass.
 for t in s.get('exhaustive_regions',[]):
  if not any(i['box_xyxy']==t['box_xyxy'] and i['source_crop_sha256']==t['source_crop_sha256'] and i['candidate_crop_sha256']==t['candidate_crop_sha256'] for i in j['items']):raise ValueError('Unreviewed exact tile: '+t['id'])
 bad=[i['id'] for i in j['items'] if i['state'] not in DONE]
 if s['candidate_sha256']!=j['candidate_sha256'] or sha(s['candidate'])!=j['candidate_sha256']:raise ValueError('Candidate changed after review.')
 if s['reference_sha256']!=j['reference_sha256'] or sha(s['reference'])!=j['reference_sha256']:raise ValueError('Reference changed after review.')
 if j['artifact_sha256'] and (not artifact or sha(artifact)!=j['artifact_sha256']):raise ValueError('Artifact changed after review.')
 if j['active'] or bad:raise ValueError('Review incomplete: '+str(bad))
 for i in j['items']:
  h=i['history'][-1]
  validate_checks(i,h.get('checks'),i['state'])
  if requirements(i) and h.get('requirements')!=requirements(i):raise ValueError('Requirements changed after observation: '+i['id'])
  if not Path(h['evidence']).exists() or sha(h['evidence'])!=h['evidence_sha256']:raise ValueError('Evidence missing or changed: '+i['id'])
  if i.get('scan_evidence_sha256') and (sha(i['evidence'])!=i['scan_evidence_sha256'] or h['evidence_sha256']!=i['scan_evidence_sha256']):raise ValueError('Current scanner evidence missing or changed: '+i['id'])
  # Legacy observations remain readable. New observations carry an explicit crop binding.
  if h.get('scan_evidence_sha256') and (h['evidence_sha256']!=h['scan_evidence_sha256'] or h.get('source_crop_sha256')!=i['source_crop_sha256'] or h.get('candidate_crop_sha256')!=i['candidate_crop_sha256']):raise ValueError('Observation does not match the reviewed crop: '+i['id'])
  if i['state']=='allowed_difference':
   p=next((p for p in j['policies'] if p['id']==h.get('policy_id')),None)
   if not p or not policy_ok(p,i):raise ValueError('Invalid allowed-difference policy: '+i['id'])
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['init','begin','record','record-batch','queue','status','rebase','check','start-discovery','abort-discovery','finish-discovery','export-regions','require-probes','import-probe','flag']);ap.add_argument('--ledger',type=Path,required=True);ap.add_argument('--scan',type=Path);ap.add_argument('--artifact',type=Path);ap.add_argument('--id');ap.add_argument('--verdict',choices=sorted(VERDICTS));ap.add_argument('--note');ap.add_argument('--evidence',type=Path);ap.add_argument('--checks',type=Path,help='JSON object of requirement name -> {verdict, note}');ap.add_argument('--observations',type=Path,help='JSON array of independent observations for record-batch');ap.add_argument('--limit',type=int,default=8,help='Maximum queue rows (default: 8)');ap.add_argument('--policies',type=Path);ap.add_argument('--policy-id');ap.add_argument('--output',type=Path);ap.add_argument('--prefix',default='fixed_');ap.add_argument('--maker-id',default='artifact-maker',help='Artifact author/session identity for independent review');args=ap.parse_args()
 try:
  if args.limit<1:raise ValueError('--limit must be positive')
  if args.action=='init':
   if args.ledger.exists():raise ValueError('Ledger exists; use rebase to retain history.')
   s=read(args.scan);assert_scan_inputs(s);j={'version':5,'canvas':s.get('canvas'),'discovery':{'state':'required','round':0},'active':None,'reference':s['reference'],'candidate':s['candidate'],'artifact':str(args.artifact.resolve()) if args.artifact else None,'reference_sha256':s['reference_sha256'],'candidate_sha256':s['candidate_sha256'],'artifact_sha256':sha(args.artifact) if args.artifact else None,'policies':read(args.policies) if args.policies else [],'items':[dict(bind_evidence(i),state='open',history=[]) for i in items(s)],'history':[]};independent_review.attach(j,args.maker_id);save(args.ledger,j);print('initialized; independent visual review required');return
  j=read(args.ledger)
  if args.action in {'queue','status'}:print_queue(j,args.action,args.limit);return
  if args.action=='abort-discovery':
   if j.get('discovery',{}).get('state') not in {'awaiting_scan','reviewing'}:raise ValueError('Only an active discovery sweep can be interrupted.')
   validate_note(args.note,strict=True)
   if not args.evidence or not args.evidence.is_file():raise ValueError('Interrupted discovery requires actual finding evidence.')
   i=find_item(j,args.id)
   event={'event':'abort_discovery','id':i['id'],'note':args.note,'previous_discovery':copy.deepcopy(j['discovery']),'bound_artifact_sha256':j.get('artifact_sha256'),'current_artifact_sha256':sha(j['artifact']) if j.get('artifact') else None,'evidence':str(args.evidence.resolve()),'evidence_sha256':sha(args.evidence),'recorded_at_ns':time.time_ns()}
   j['history'].append(event);i['history'].append(dict(event,verdict='fix_required',kind='interrupted_discovery'));i['state']='fix_required';i['pending_fix']=True
   independent_review.track_local(j,i,i['history'][-1])
   # Keep old bindings and evidence: this action neither accepts edits nor carries a pass.
   # A normal rebase, local review and new discovery sweep remain mandatory.
   j['active']=None;j['discovery']={'state':'required','round':j['discovery'].get('round',0)};save(args.ledger,j);print('Discovery interrupted; finding reopened. Rebase and repair before a new full sweep.');return
  if args.action=='require-probes':
   if not args.checks:raise ValueError('require-probes needs --checks contract.json')
   acceptance_probes.register(j,args.checks);save(args.ledger,j);print('Occlusion obligations registered; current evidence required.');return
  if args.action=='import-probe':
   if not args.evidence:raise ValueError('import-probe needs --evidence result.json')
   acceptance_probes.attach(j,args.evidence);save(args.ledger,j);print(json.dumps({'probe_pass':j['acceptance_probes']['latest']['pass']}));return
  if args.action=='flag':
   assert_current_inputs(j);validate_note(args.note,strict=True)
   if not args.evidence or not args.evidence.is_file():raise ValueError('External finding requires actual evidence')
   i=find_item(j,args.id);i['state']='fix_required';i['pending_fix']=True
   i['history'].append({'verdict':'fix_required','kind':'external_finding','note':args.note,'artifact_sha256':j.get('artifact_sha256'),'evidence':str(args.evidence.resolve()),'evidence_sha256':sha(args.evidence),'recorded_at_ns':time.time_ns()})
   independent_review.track_local(j,i,i['history'][-1])
   j['discovery']['state']='required';save(args.ledger,j);print('Finding reopened and blocks delivery: '+i['id']);return
  if args.action=='export-regions':export_regions(j,args);return
  if args.action=='record-batch':
   if not args.observations:raise ValueError('record-batch requires --observations JSON')
   updated,results=record_batch(j,read(args.observations));save(args.ledger,updated);print(json.dumps({'recorded':results,'active':updated['active']},ensure_ascii=False));return
  if args.action=='rebase':
   if j.get('artifact_sha256') and not args.artifact:raise ValueError('This ledger is bound to an artifact; rebase requires --artifact and cannot clear that binding.')
   s=read(args.scan);assert_scan_inputs(s)
   if s['reference_sha256']!=j['reference_sha256']:raise ValueError('Reference changed; requires a new review.')
   dis=j.get('discovery',{'state':'required','round':0});outer=dis['state']=='awaiting_scan'
   if outer:
    if s.get('started_at_ns',0)<=dis['requested_at_ns'] or not s.get('run_id') or s['run_id']==dis.get('previous_run_id'):raise ValueError('A genuinely new scan after start-discovery is required.')
    if s['candidate_sha256']!=dis['candidate_sha256'] or (args.artifact and sha(args.artifact)!=dis['artifact_sha256']):raise ValueError('Candidate changed during final discovery; finish local repair first.')
   forced={tuple(n['box_xyxy']) for n in s['proposals']+s['coverage']+s.get('exhaustive_regions',[])} if outer else set()
   old=j['candidate_sha256'];previous_active=j['active'];fresh=[bind_evidence(i) for i in items(s)];seen=set();matched_ids=set();resets=0
   carried={n['ledger_id']:n for n in fresh if n.get('ledger_id')}
   for i in j['items']:
    if i['id'] in carried and carried[i['id']]['box_xyxy']!=i['box_xyxy']:raise ValueError('A carried fixed ID changed coordinates: '+i['id'])
   for i in j['items']:
    i['pending_fix']=i.get('pending_fix',False) or i['state'] in {'fix_required','uncertain'}
    same_box=[n for n in fresh if n['box_xyxy']==i['box_xyxy']]
    n=carried.get(i['id']) or next((n for n in same_box if n['id']==i['id']),None) or (same_box[-1] if same_box else None)
    unchanged=n and n['source_crop_sha256']==i['source_crop_sha256'] and n['candidate_crop_sha256']==i['candidate_crop_sha256'] and n['scan_evidence_sha256']==i.get('scan_evidence_sha256',n['scan_evidence_sha256'])
    req=dict(requirements(i));req.update(requirements(n) if n else {})
    if not unchanged or tuple(i['box_xyxy']) in forced or req!=requirements(i):i['state']='open';resets+=1
    if req:i['requirements']=req
    if n:
     i.update({k:n[k] for k in ['source_crop_sha256','candidate_crop_sha256','evidence','scan_evidence_sha256','channel_signals']});seen.add(tuple(n['box_xyxy']));matched_ids.add(n['id'])
    else:
     # Old fixed boxes must also be included as source regions in the next scan.
     raise ValueError('Missing fixed box in rescan; export old ledger boxes to --regions. IDs must not drift with rankings.')
   known={i['id'] for i in j['items']};source_ids={n['id'] for n in s.get('source_regions',[])}
   for n in fresh:
    # New named source obligations survive even when their box overlaps a prior proposal.
    if tuple(n['box_xyxy']) not in seen or (n['id'] in source_ids and n['id'] not in matched_ids and n['id'] not in known and not n.get('ledger_id')):
     k=n['id'];num=2
     while k in known:k=n['id']+'_'+str(num);num+=1
     known.add(k);j['items'].append(dict(n,id=k,state='open',history=[]));seen.add(tuple(n['box_xyxy']))
   if dis['state']=='reviewing':j['history'].append({'event':'discovery_interrupted_by_rescan','round':dis.get('round'),'found_problem':dis.get('found_problem',False),'scan_run_id':dis.get('scan_run_id')})
   j['version']=5 if j.get('independent_review') else 4;j['canvas']=s.get('canvas') or j.get('canvas')
   j['last_scan_run_id']=s.get('run_id')
   j['discovery']=dict(state='reviewing',round=dis.get('round',0)+1,scan_run_id=s['run_id'],scan_sha256=sha(args.scan),candidate_sha256=s['candidate_sha256'],artifact_sha256=sha(args.artifact) if args.artifact else None,found_problem=False) if outer else dict(state='required',round=dis.get('round',0))
   j.update(active=previous_active,reference=s['reference'],candidate=s['candidate'],artifact=str(args.artifact.resolve()) if args.artifact else None,candidate_sha256=s['candidate_sha256'],artifact_sha256=sha(args.artifact) if args.artifact else None);j['history'].append({'event':'rebase','previous_candidate':old,'candidate':s['candidate_sha256'],'invalidated':resets});save(args.ledger,j);print(json.dumps({'invalidated':resets,'items':len(j['items'])}));return
  if args.action in {'check','start-discovery','finish-discovery'}:
   s=read(args.scan);assert_local_complete(j,s,args.artifact);dis=j.get('discovery',{'state':'required','round':0})
   if args.action=='start-discovery':
    j['discovery']={'state':'awaiting_scan','round':dis.get('round',0),'requested_at_ns':time.time_ns(),'previous_run_id':s.get('run_id'),'candidate_sha256':j['candidate_sha256'],'artifact_sha256':j['artifact_sha256']}
    j['history'].append({'event':'start_discovery','requested_at_ns':j['discovery']['requested_at_ns']});save(args.ledger,j);print('Run a fresh whole-canvas scan, then rebase and review the reopened evidence.');return
   if args.action=='finish-discovery':
    if dis['state']!='reviewing' or dis.get('found_problem'):raise ValueError('Discovery is not clean; complete repairs, then start another discovery scan.')
    if s.get('run_id')!=dis.get('scan_run_id') or sha(args.scan)!=dis.get('scan_sha256'):raise ValueError('Discovery scan changed.')
    if not args.note:raise ValueError('Record the scope and outcome of the fresh whole-canvas observation.')
    dis.update(state='passed',note=args.note,completed_at_ns=time.time_ns());j['discovery']=dis;j['history'].append({'event':'finish_discovery','round':dis['round'],'note':args.note});save(args.ledger,j);print('Final discovery review recorded.');return
   if dis['state']!='passed' or s.get('run_id')!=dis.get('scan_run_id') or sha(args.scan)!=dis.get('scan_sha256'):raise ValueError('Local queue completion is insufficient. A fresh, completed discovery sweep is required.')
   independent=independent_review.check(j)
   print(json.dumps({'complete':True,'reviewed':len(j['items']),'discovery_round':dis['round'],'independent_review':independent,'scope':'Review records, current independent discovery and per-issue rechecks, artifact consistency; semantic correctness and actual reviewer independence are not proven.'}));return
  if args.action=='begin':
   i=begin_item(j,args.id);result={'id':i['id'],'state':i['state']}
  else:
   result=record_observation(j,{'id':args.id,'verdict':args.verdict,'note':args.note,'evidence':args.evidence,'policy_id':args.policy_id,'checks':read(args.checks) if args.checks else None})
  save(args.ledger,j);print(json.dumps(result))
 except (ValueError,TypeError,KeyError,OSError) as e:ap.exit(2,str(e)+'\n')
if __name__=='__main__':main()
