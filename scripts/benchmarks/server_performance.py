#!/usr/bin/env python3
"""Measure an OpenAI-compatible deployment. Secrets are read from a private JSON file.
Reported percentiles are descriptive for this small sample, not an SLA.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
import httpx


async def main(args):
    cfg=json.loads(args.config.read_text())
    records=[]
    async with httpx.AsyncClient(timeout=300) as client:
        async def sample(index, concurrency):
            started=time.monotonic();first=None;parts=[];usage={};finish=None
            payload={'model':cfg['model'],'messages':[{'role':'system','content':'Answer concisely.'},{'role':'user','content':'Write the integers from 1 to 16 separated by spaces. Do not explain.'}],'max_tokens':64,'temperature':0,'stream':True}
            row={'index':index,'concurrency':concurrency}
            try:
                async with client.stream('POST',cfg['base_url'].rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+cfg['api_key']},json=payload) as response:
                    row['http_status']=response.status_code
                    if response.status_code!=200:
                        await response.aread(); row['error']='upstream_http_error'
                    else:
                        async for line in response.aiter_lines():
                            if not line.startswith('data:'):continue
                            raw=line[5:].strip()
                            if raw=='[DONE]':break
                            event=json.loads(raw);usage=event.get('usage') or usage
                            for choice in event.get('choices',[]):
                                delta=choice.get('delta',{});content=delta.get('content') or ''
                                if content:
                                    if first is None:first=time.monotonic()-started
                                    parts.append(content)
                                finish=choice.get('finish_reason') or finish
                row.update(seconds=time.monotonic()-started,ttft_seconds=first,finish_reason=finish,content_characters=len(''.join(parts)),usage=usage)
                if row['http_status']==200 and not parts:row['error']='no_visible_content'
            except Exception as error:
                row.update(seconds=time.monotonic()-started,error=type(error).__name__)
            records.append(row);print(json.dumps(row),flush=True)
        started=time.monotonic()
        for i in range(args.sequential):await sample(i+1,1)
        for batch in range(args.concurrent_batches):
            await asyncio.gather(*(sample(args.sequential+batch*2+i+1,2) for i in range(2)))
        elapsed=time.monotonic()-started
    successful=[r for r in records if r.get('http_status')==200 and 'error' not in r]
    def percentiles(values):
        values=sorted(values)
        return {f'p{int(q*100)}':values[max(0, math.ceil(len(values)*q)-1)] for q in (.5,.95,.99)} if values else None
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'model':cfg['model'],'method':'Streaming chat/completions; fixed 1..16 counting prompt, max_tokens=64, temperature=0; sequential then concurrency=2. No retries.','requests':len(records),'successful':len(successful),'status_counts':dict(Counter(str(r.get('http_status','transport_error')) for r in records)),'wall_seconds':elapsed,'percentile_method':'nearest-rank, includes all successful requests including first request','latency_seconds':percentiles([r['seconds'] for r in successful]),'ttft_seconds':percentiles([r['ttft_seconds'] for r in successful if r.get('ttft_seconds') is not None]),'samples':records,'limitations':'Small deployment-specific sample, includes network/proxy/model-load latency. Provider inference hardware is not assumed to match the EduNote application server. Token throughput is omitted when the upstream stream does not report usage.'}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--sequential',type=int,default=4);p.add_argument('--concurrent-batches',type=int,default=2);a=p.parse_args();asyncio.run(main(a))
