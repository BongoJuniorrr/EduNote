#!/usr/bin/env python3
"""Bounded, read-only mixed HTTP load against an isolated release deployment."""
import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import time
import httpx


async def main(args):
    routes=['/','/settings','/edu_studio','/api/v1/notebook/list','/api/v1/knowledge/list','/api/v1/dashboard/recent?limit=10','/api/v1/config/llm','/api/v1/mission/health']
    auth=("owner", args.password_file.read_text().strip()) if args.password_file else None
    results=[];counter=iter(range(args.requests));started=time.monotonic()
    async with httpx.AsyncClient(timeout=30, auth=auth, limits=httpx.Limits(max_connections=args.concurrency)) as client:
        async def worker():
            for index in counter:
                route=routes[index%len(routes)];ts=time.monotonic()
                try:
                    response=await client.get(args.base_url.rstrip('/')+route)
                    results.append({'path':route,'status':response.status_code,'seconds':time.monotonic()-ts})
                except Exception as error:
                    results.append({'path':route,'status':'transport_error','seconds':time.monotonic()-ts,'error':type(error).__name__})
        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
    elapsed=time.monotonic()-started;latency=sorted(r['seconds'] for r in results)
    def quantile(q):return latency[min(len(latency)-1,int(q*(len(latency)-1)))]
    codes=Counter(str(r['status']) for r in results)
    result={'scope':'Finite read-only mixed UI/API workload against restored QA release; does not establish GPU/LLM concurrent-generation capacity.',
            'requests':len(results),'concurrency':args.concurrency,'elapsed_seconds':elapsed,'requests_per_second':len(results)/elapsed,
            'status_counts':dict(codes),'latency_seconds':{f'p{int(q*100)}':quantile(q) for q in (.5,.95,.99)},
            'passes':all(r['status']==200 for r in results),'samples':results}
    args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='samples'}))
    if not result['passes']:raise SystemExit(1)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-url',required=True);p.add_argument('--requests',type=int,default=400);p.add_argument('--concurrency',type=int,default=8);p.add_argument('--output',type=Path,required=True);p.add_argument('--password-file',type=Path)
    args=p.parse_args()
    if not 1<=args.concurrency<=32 or not 1<=args.requests<=5000:p.error('Use 1..32 workers, 1..5000 requests')
    args.output.parent.mkdir(parents=True,exist_ok=True);asyncio.run(main(args))
