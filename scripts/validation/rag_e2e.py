#!/usr/bin/env python3
"""Real PDF ingestion, persistent E5 index and queued retrieval in disposable QA."""
import argparse
import asyncio
import json
from pathlib import Path
import time
import uuid
import httpx
import fitz


def pdf(text):
    with fitz.open() as doc:
        page=doc.new_page();page.insert_textbox(fitz.Rect(40,40,550,750),text,fontsize=12)
        return doc.tobytes()


async def main(base, output):
    started=time.monotonic();name='qa_rag_'+uuid.uuid4().hex[:8];events=[]
    async with httpx.AsyncClient(base_url=base.rstrip('/')+'/api/v1',timeout=330) as client:
        async def call(method,path,**kwargs):
            r=await client.request(method,path,**kwargs);r.raise_for_status();return r.json()
        async def ready():
            for _ in range(180):
                d=await call('GET',f'/knowledge/{name}/progress')
                stage=d.get('stage',d.get('progress',{}).get('stage'))
                if stage=='completed':return d
                if stage=='error':raise AssertionError(d)
                await asyncio.sleep(2)
            raise TimeoutError('KB initialization')
        async def query(question,expected):
            d=await call('POST','/knowledge/query',json={'kb_name':name,'query':question,'provider':'llamaindex','mode':'naive'})
            jid=d['job']['id']
            for _ in range(150):
                job=(await call('GET',f'/jobs/{jid}'))['job']
                if job['status']=='completed':
                    result=job.get('result',{});assert expected.lower() in json.dumps(result).lower(),result
                    assert 'sources' in json.dumps(result),result
                    return {'completed':True,'expected_content_found':True,'source_metadata_present':True}
                if job['status']=='failed':raise AssertionError(job.get('error'))
                await asyncio.sleep(2)
            raise TimeoutError('Retrieval job')
        await call('POST','/knowledge/create',data={'name':name,'rag_provider':'llamaindex'},files={'files':('orchid.pdf',pdf('ORCHID LAB FIELD NOTES\nThe orchid specimen ORCHID-73 has violet petals and absorbs moisture through aerial roots.\nThe observation date was October 28. The sample code is VIOLET73.'),'application/pdf')})
        await ready();events.append('PDF parsed and indexed')
        first=await query('What color are the petals of specimen ORCHID-73?','violet')
        await call('POST',f'/knowledge/{name}/upload',files={'files':('telescope.pdf',pdf('ASTRONOMY LAB NOTES\nThe telescope ASTRA-42 has a mirror diameter of 420 millimeters.\nThe observatory is named HIGHLAND42.'),'application/pdf')})
        await ready();events.append('Incremental PDF upload indexed')
        second=await query('What is the mirror diameter of telescope ASTRA-42?','420')
        output.write_text(json.dumps({'passed':True,'seconds':time.monotonic()-started,'events':events,'initial_retrieval':first,'incremental_retrieval':second,'kb_name':name,'scope':'Real PDF parser + local multilingual E5 + persisted LlamaIndex + durable queue worker and source metadata. No mocked embeddings.'},indent=2)+'\n')
        print(output.read_text())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-url',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--isolated-workspace',action='store_true',required=True)
    a=p.parse_args();asyncio.run(main(a.base_url,a.output))
