import asyncio
import json
from unittest.mock import AsyncMock
from src.agents.mission.agents.planner_agent import PlannerAgent
from src.agents.mission.schemas import MissionBrief, MissionPlanRequest


def test_planner_filters_unavailable_capabilities_and_normalizes_dependencies():
    agent=PlannerAgent.__new__(PlannerAgent)
    agent.get_prompt=lambda name, default='': default
    agent.call_llm=AsyncMock(return_value=json.dumps({'steps':[
        {'step_id':'a','step_type':'research_brief','title':'Unavailable KB'},
        {'step_id':'b','step_type':'knowledge_map','title':'Available notes','depends_on':['a']},
        {'step_id':'c','step_type':'final_dossier','depends_on':['b']},
        {'step_id':'d','step_type':'review','depends_on':['c']},
    ]}))
    steps=asyncio.run(agent.process(MissionBrief(working_title='Test',objective='Use notes'),MissionPlanRequest(goal='Prepare study notes'),capabilities={'has_primary_kb':False,'has_notebooks':True}))
    assert [s.step_type for s in steps]==['knowledge_map','final_dossier','review']
    assert [s.step_id for s in steps]==['step_1','step_2','step_3']
    assert [s.depends_on for s in steps]==[[],['step_1'],['step_2']]
