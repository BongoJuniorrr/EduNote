import asyncio
from src.agents.guide.agents.locate_agent import LocateAgent


def run(response):
    agent=LocateAgent.__new__(LocateAgent)
    agent.get_prompt=lambda name:'Analyze notes.' if name=='system' else '{records_content}'
    async def call(**kwargs):return response
    agent.call_llm=call
    return asyncio.run(agent.process('note','Arithmetic',[{'type':'note','title':'Addition','output':'Two plus three is five.'}]))


def test_guided_learning_accepts_json_wrapped_in_model_markdown():
    result=run('```json\n{"knowledge_points":[{"knowledge_title":"Addition","knowledge_summary":"Combining quantities."}]}\n```')
    assert result['success'] and result['knowledge_points'][0]['knowledge_title']=='Addition'


def test_guided_learning_does_not_invent_points_from_invalid_model_text():
    result=run('No usable structured response.')
    assert result['knowledge_points']==[]
