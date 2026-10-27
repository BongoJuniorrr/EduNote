#!/usr/bin/env python3
"""Real-provider workflow checks. Run ONLY against an isolated restored workspace.
Creates QA notebooks, KBs, sessions and artifacts. Does not mock LLM responses.
"""
import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import time
import uuid
import httpx
import websockets


async def main(base, output, only=None):
    api = base.rstrip('/') + '/api/v1'
    wsbase = api.replace('http://', 'ws://').replace('https://', 'wss://')
    results = []
    async with httpx.AsyncClient(timeout=330) as client:
        async def request(method, path, **kwargs):
            response = await client.request(method, api + path, **kwargs)
            response.raise_for_status()
            return response.json()

        async def websocket(path, payload, terminal='result', limit=1200):
            events = []; counts = Counter()
            async with asyncio.timeout(limit):
                async with websockets.connect(wsbase + path, max_size=16*1024*1024, ping_timeout=300) as ws:
                    await ws.send(json.dumps(payload))
                    async for message in ws:
                        event = json.loads(message); counts[event.get('type','unknown')] += 1
                        if event.get('type') == 'error':
                            raise AssertionError(str(event)[:800])
                        if event.get('type') in ('result', 'batch_summary', 'session', 'question'):
                            events.append(event)
                        if event.get('type') == terminal:
                            return events, dict(counts)
            raise AssertionError('WebSocket closed without terminal result')

        async def check(name, action):
            if only and name not in only and not (name == "notebook_create_record_reload" and only != {"settings_live_llm"}): return
            started = time.monotonic()
            try:
                evidence = await action()
                entry = {'name': name, 'passed': True, 'seconds':time.monotonic()-started, 'evidence': evidence}
            except Exception as error:
                entry = {'name':name, 'passed':False,'seconds':time.monotonic()-started,'error':f'{type(error).__name__}: {error}'}
            results.append(entry); output.write_text(json.dumps({'scope':'Real backend/provider workflows in isolated restored workspace; browser checks recorded separately.','results':results},indent=2)+'\n')
            print(json.dumps(entry),flush=True)

        ids = {}
        async def settings():
            configs = (await request('GET','/config/llm'))['configs']
            active = next(c for c in configs if c.get('is_active'))
            data = await request('POST',f"/config/llm/{active['id']}/test")
            assert data['success'],data
            return {'model':active['model'],'connection_success':True}
        await check('settings_live_llm', settings)

        async def notebook():
            data = await request('POST','/notebook/create',json={'name':'QA recovery '+uuid.uuid4().hex[:8]})
            nb=data.get('notebook',data);ids['notebook']=nb['id']
            await request('POST',f"/notebook/{nb['id']}/records",json={'type':'note','title':'Arithmetic source','user_query':'Study addition','output':'Addition combines quantities. Two plus three equals five. Six plus seven equals thirteen.'})
            restored=await request('GET',f"/notebook/{nb['id']}")
            assert 'Arithmetic source' in json.dumps(restored)
            return {'created_and_reloaded':True}
        await check('notebook_create_record_reload',notebook)

        async def canvas():
            d=await request('POST','/notebook/canvas/sessions',json={'title':'QA persistent canvas','notebook_id':ids['notebook']});sid=d['session']['session_id']
            overlay={'id':'qa-text','type':'text','x':20,'y':40,'w':240,'h':60,'text':'Two plus three equals five.'}
            await request('POST',f'/notebook/canvas/sessions/{sid}/strokes:batch',json={'page_index':0,'overlays':[overlay],'strokes':[],'replace_page':True})
            d=await request('GET',f'/notebook/canvas/sessions/{sid}');assert 'Two plus three' in json.dumps(d)
            return {'session_saved_and_reloaded':True}
        await check('canvas_save_reload',canvas)

        async def chat():
            events,counts=await websocket('/chat',{'message':'Remember the codeword ORCHID. Reply with ORCHID only.','enable_rag':False,'enable_web_search':False})
            sid=next(e['session_id'] for e in events if e['type']=='session')
            second,counts2=await websocket('/chat',{'message':'What codeword did I ask you to remember? Reply with the codeword only.','session_id':sid,'enable_rag':False,'enable_web_search':False})
            assert 'ORCHID' in str(second[-1]).upper()
            saved=await request('GET',f'/chat/sessions/{sid}');assert 'ORCHID' in json.dumps(saved)
            return {'two_turn_memory':True,'history_persisted':True,'events':[counts,counts2]}
        await check('chat_two_turn_persistence',chat)

        async def cowriter():
            d=await request('POST','/co_writer/edit',json={'text':'Plants use sunlight to make food. This process is photosynthesis.','instruction':'Rewrite as one clear sentence for a beginner.','action':'shorten'})
            assert len(json.dumps(d))>50
            return {'response_keys':list(d)}
        await check('co_writer_real_edit',cowriter)

        async def guide():
            d=await request('POST','/guide/create_session',json={'notebook_id':ids['notebook']});assert d.get('success') and d.get('session_id'),d.get('error','Guide creation failed');sid=d['session_id']
            start=await request('POST','/guide/start',json={'session_id':sid})
            assert start and not start.get('error'),start
            reply=await request('POST','/guide/chat',json={'session_id':sid,'message':'Explain why two plus three is five, briefly.'})
            assert reply and not reply.get('error'),reply
            saved=await request('GET',f'/guide/session/{sid}');assert saved
            return {'created_started_chat_reloaded':True,'start_keys':list(start),'chat_keys':list(reply)}
        await check('guided_learning_start_chat_reload',guide)

        async def studio():
            catalog=await request('GET','/edu-studio/templates'); workflows=[w['id'] for w in catalog['workflows']]
            done=[]
            for workflow in workflows:
                d=await request('POST','/edu-studio/run',json={'workflow':workflow,'title':'QA '+workflow,'language':'en','source_text':'Addition combines quantities. Two plus three equals five. Six plus seven equals thirteen. A 15 minute beginner arithmetic class.','instructions':'Keep the output concise. Follow the required JSON schema.','settings':{'slide_count':2,'question_count':2}})
                assert d.get('success') and d.get('result',{}).get('deliverable_markdown'),(workflow,d)
                rid=d.get('run_id');
                if rid: assert await request('GET',f'/edu-studio/runs/{rid}')
                done.append(workflow); print('studio workflow completed: '+workflow,flush=True)
            return {'workflows':done,'count':len(done)}
        await check('edu_studio_all_workflows',studio)

        async def solve():
            events,counts=await websocket('/solve',{'question':'Compute 6 + 7. Give the final integer and one short explanation. No web search is needed.','kb_name':''})
            answer=events[-1].get('final_answer',''); assert '13' in str(answer),str(events[-1])[:500]
            return {'correct_answer':True,'events':counts}
        await check('solver_multi_agent_real_answer',solve)

        async def question():
            events,counts=await websocket('/question/generate',{'requirement':{'knowledge_point':'Single digit addition','difficulty':'easy','question_type':'choice','additional_requirements':'Create one multiple-choice question: 2+3 with one correct answer 5.'},'count':1,'kb_name':''},terminal='complete')
            summary=next(e for e in events if e['type']=='batch_summary');assert summary['completed']==1 and summary['failed']==0,summary
            return {'batch_completed':1,'events':counts}
        await check('question_generation_real_coordinator',question)

        async def research():
            events,counts=await websocket('/research/run',{'topic':'Explain single digit addition with two examples, using only basic arithmetic. Keep the research report short.','plan_mode':'quick','enabled_tools':[],'skip_rephrase':True,'kb_name':''},terminal='complete')
            result=next(e for e in events if e['type']=='result');assert len(json.dumps(result))>100
            return {'report_generated':True,'events':counts}
        await check('deep_research_real_report',research)

        async def mission():
            d=await request('POST','/mission/plan',json={'goal':'Create a concise study brief on addition for a beginner. Use notebook sources and one short final dossier.','preset':'custom','notebook_ids':[ids['notebook']],'desired_outputs':['study_brief'],'research_depth':'quick','constraints':'Do not use external web tools. Keep output short.'})
            run=d['run'];rid=run['run_id']
            await request('POST',f'/mission/runs/{rid}/approve')
            events,counts=await websocket('/mission/run',{'run_id':rid},limit=1800)
            final=events[-1]['run'];assert final['status']=='completed',final['status']
            assert final['artifacts']
            assert all(step['status'] == 'completed' for step in final['plan']), [(s['step_type'],s['status']) for s in final['plan']]
            return {'planned_approved_executed':True,'artifacts':len(final['artifacts']),'events':counts}
        await check('mission_plan_approve_execute',mission)
    if any(not r['passed'] for r in results): raise SystemExit(1)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-url',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--isolated-workspace',action='store_true',required=True,help='Required acknowledgement: this workspace is disposable')
    p.add_argument('--only',help='Comma-separated scenario names for targeted reruns')
    args=p.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True);asyncio.run(main(args.base_url,args.output,set(args.only.split(',')) if args.only else None))
