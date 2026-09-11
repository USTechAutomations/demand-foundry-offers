"""Replay synthetic source snapshots against a fresh isolated PostgreSQL.
0 matches, 1 mismatch, 2 unavailable/malformed evidence. No source execution here.
"""
import json,subprocess,uuid,time,sys
from decimal import Decimal
from pathlib import Path
P=Path(__file__).resolve().parent
name='usta-migration-replay-'+uuid.uuid4().hex[:10]
started=False
def run(args,stdin=None):
 r=subprocess.run(args,input=stdin,text=True,capture_output=True,timeout=45)
 if r.returncode:raise RuntimeError('command unavailable/failed: '+args[0]+' '+r.stderr[:300])
 return r.stdout.strip()
def sql(q):return run(['docker','exec','-i',name,'psql','-U','postgres','-X','-qAt','-v','ON_ERROR_STOP=1'],q)
def read(f):return json.loads((P/f).read_text(),parse_float=Decimal)
def compare(table,query,label):
 if not isinstance(table,list) or not table or not all(isinstance(x,str) for x in table[0]):raise ValueError('malformed source table')
 headers=table[0]
 if len(set(headers))!=len(headers) or any(len(row)!=len(headers) for row in table[1:]):raise ValueError('malformed source rows')
 expected=[{k:Decimal(v) for k,v in zip(headers,row)} for row in table[1:]]
 actual=json.loads(sql("SELECT coalesce(json_agg(t),'[]'::json) FROM ("+query+") t"),parse_float=Decimal)
 return {'case':label,'status':'PASS' if expected==actual else 'FAIL','rows':len(expected)}
def main():
 global started
 tables=read('source-tables.json')[1:];cases=read('cases.json');precision=read('source-precision-tables.json')
 if len(tables)!=9 or len(cases)!=9 or len(precision)!=2:raise ValueError('source evidence coverage missing')
 run(['docker','run','--pull','never','-d','--name',name,'--network','none','--memory','384m','--cpus','1','--pids-limit','100','--tmpfs','/var/lib/postgresql/data:rw,size=160m','-e','POSTGRES_HOST_AUTH_METHOD=trust','postgres:15.7-alpine']);started=True
 for _ in range(40):
  r=subprocess.run(['docker','exec',name,'pg_isready','-h','127.0.0.1','-U','postgres'],capture_output=True,timeout=5)
  if r.returncode==0:break
  time.sleep(.25)
 else:raise RuntimeError('PostgreSQL startup unavailable')
 sql((P/'setup.sql').read_text()+(P/'target.sql').read_text())
 results=[compare(t,c[2],c[0]) for t,c in zip(tables,cases)]
 sql("INSERT INTO orders VALUES (80,80,999999999999999999.99,'2024-02-10','paid'),(81,80,999999999999999999.99,'2024-02-11','paid')")
 results.extend(compare(t,q,'wide-decimal-'+str(i)) for i,(t,q) in enumerate(zip(precision,['SELECT * FROM customer_report(80,NULL)','SELECT * FROM ranked_orders(80)'])))
 print(json.dumps({'scope':'SYNTHETIC: saved SQL Server rows vs fresh PostgreSQL; not a customer migration or native metadata proof','results':results},indent=2))
 return 0 if all(r['status']=='PASS' for r in results) else 1
try:
 code=main()
except Exception as e:
 print(json.dumps({'status':'UNKNOWN','reason':str(e)[:400]}));code=2
finally:
 if started:
  try:run(['docker','rm','-f',name])
  except Exception as e:print(json.dumps({'cleanup':'UNKNOWN','container':name,'reason':str(e)[:200]}));code=2
raise SystemExit(code)
