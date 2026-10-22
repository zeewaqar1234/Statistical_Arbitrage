import sys, json, math, csv, gzip, fcntl, hashlib
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
sys.path.insert(0,str(Path.cwd()))
from src.crypto_hft_tool.quote_data import read_quotes, midpoint, vwap
out=Path('reports/tool_briefing/.build')
qfile=Path('data/quotes/2026-10-11.csv.gz')
with qfile.open('rb') as f:
    fcntl.flock(f,fcntl.LOCK_SH)
    blob=f.read()
(out/'quotes_snapshot.csv.gz').write_bytes(blob)
result={'file':str(qfile),'sha256':hashlib.sha256(blob).hexdigest(),'markets':{}}
for symbol in ('btc-eur','eth-eur'):
    rows=read_quotes(out/'quotes_snapshot.csv.gz',symbol)
    measures=[]
    signed=[]
    for r in rows:
        if not r['fresh']: continue
        a,b=midpoint(r['a']),midpoint(r['b'])
        q=1000/a
        abid,aask=vwap(r['a'],'sell',q),vwap(r['a'],'buy',q)
        bbid,bask=vwap(r['b'],'sell',q),vwap(r['b'],'buy',q)
        if None in (abid,aask,bbid,bask): continue
        signed.append((a-b)/b*10000)
        spread1=(abid-bask)/((abid+bask)/2)*10000
        spread2=(bbid-aask)/((bbid+aask)/2)*10000
        measures.append(max(spread1,spread2))
    result['markets'][symbol]={'rows':len(rows),'usable_rows':len(measures),'start':datetime.fromtimestamp(rows[0]['ts']/1000,timezone.utc).isoformat(),'end':datetime.fromtimestamp(rows[-1]['ts']/1000,timezone.utc).isoformat(),'minutes':(rows[-1]['ts']-rows[0]['ts'])/60000,'mean_signed_mid_bps':float(np.mean(signed)),'mean_best_exec_bps':float(np.mean(measures)),'median_best_exec_bps':float(np.median(measures)),'max_best_exec_bps':float(np.max(measures)),'above_17_bps':sum(x>17 for x in measures),'above_9_bps':sum(x>9 for x in measures)}
(out/'evidence.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
