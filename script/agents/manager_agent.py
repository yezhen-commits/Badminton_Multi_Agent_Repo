from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from agents.subagent import call_search_web_agent, call_database_agent, call_mcp_agent, call_answer_creation_agent
from resource.agent_prompt import get_agent_system_prompt

search_web_prompt,mongodb_prompt, answer_creation_prompt,manager_prompt = get_agent_system_prompt()

def create_manager_agent():
    return create_agent(
        model="gpt-5.4-mini",
        tools=[call_answer_creation_agent, call_mcp_agent, call_database_agent, call_search_web_agent],
        system_prompt=manager_prompt,
        middleware=[
            SummarizationMiddleware(model="gpt-5.4-nano", trigger=("tokens", 1000), keep=("messages", 20))
        ],
        checkpointer=InMemorySaver()
    ).with_config({"recursion_limit": 75})
    