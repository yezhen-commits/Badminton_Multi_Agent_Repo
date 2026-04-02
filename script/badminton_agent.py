from dotenv import load_dotenv
from pprint import pprint
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_community.utilities import SQLDatabase
from langchain.tools import tool
from typing import List, Any, Optional
from pydantic import BaseModel
from tavily import TavilyClient
import os
import json
import wikipedia as wk
from typing import Dict, Any, List
from langchain.agents import create_agent
from langchain.messages import HumanMessage,AIMessage
from langchain.agents.middleware import SummarizationMiddleware
from langgraph.checkpoint.memory import InMemorySaver
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse 
from contextlib import asynccontextmanager
from resource.chat_database import start_database , save_chat , save_message , get_all_chats , get_messages_by_thread ,delete_chat_by_thread
from resource.agent_prompt import get_agent_system_prompt

class QueryResult(BaseModel):
    success: bool
    data: Optional[List[Any]] = None
    error: Optional[str] = None
    
mcp_prompt, mcp_tools = None,None
block_word_list = ["drop", "delete", "update", "insert", "alter"]

load_dotenv()

search_web_prompt,database_prompt, answer_creation_prompt,manager_prompt = get_agent_system_prompt()

"""format is mysql+mysqlconnector://user:password@localhost:3306/badminton_player_database"""

mysql_uri = "mysql+mysqlconnector://:@localhost:3306/badminton_player_database"
db = SQLDatabase.from_uri(mysql_uri)

search_engine = TavilyClient()

class ChatRequest(BaseModel):
    message: str
    thread_id: str 


"Setup Agent"
async def start_MCP():
    badminton_client= MultiServerMCPClient(
        {
            "Badminton_MCP_server":{
                "transport":"stdio",
                "command":"python",
                "args":["resource/badminton_mcp.py"],
            }
        }
    )

    mcp_prompt = await badminton_client.get_prompt("Badminton_MCP_server","prompt")
    mcp_prompt = mcp_prompt[0].content
    mcp_tools = await badminton_client.get_tools()
    return mcp_prompt, mcp_tools

@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_prompt, mcp_tools
    mcp_prompt, mcp_tools = await start_MCP()
    start_database()
    
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
   
@tool 
async def query_mysql(query: str): 
    """ 
    DO NOT run any query that contain the word drop,delete, update, insert and alter. You can run query on any table in the database. Execute a MySQL query safely. 

    """ 
    # Check for forbidden keywords 
    if any(keyword in query.lower() for keyword in block_word_list): 
        return QueryResult(
            success= False,
            error =  "Query contain blocked word"
        ).model_dump()
    
    try: 
        result = db.run(query) # your existing MySQL execution function 
        return QueryResult(
            success = True,
            data = result
        ).model_dump()
    
    except Exception as e: 
        return QueryResult(
            success = False,
            error = f"Error running query: {str(e)}"
        ).model_dump()
        
@tool
async def search_web(query:str)->Dict[str,Any]:
    """
    Use this tool to search the web for information 
    """
    
    return search_engine.search(query)

@tool
async def search_wikipedia(query: str) -> Dict[str, Any]:
    """
    Use this tool to search wikipedia for information such as definition
    """
    try:
        search_results = wk.search(query, results=3)

        if not search_results:
            return {"error": "No results found"}

        results: List[Dict[str, Any]] = []

        for title in search_results:
            try:
                page = wk.page(title)

                results.append({
                    "title": page.title,
                    "summary": page.summary[0:1000]
                })

            except Exception as e:
                print(f"Error: {str(e)}")
                continue

        if not results:
            return {"error": "No valid pages found"}

        return {
            "query": query,
            "results": results
        }

    except Exception as e:
        return {"error": f"Error: {str(e)}"}
    
search_web_agent = create_agent(
    model = "gpt-5.4-nano",
    tools = [search_wikipedia,search_web],
    system_prompt = search_web_prompt
)

database_agent = create_agent(
    model= "gpt-5.4-nano",
    tools = [query_mysql],
    system_prompt = database_prompt
)

mcp_agent =  create_agent(
    model = "gpt-5.4-nano",
    tools = mcp_tools,
    system_prompt = mcp_prompt
)

answer_creation_agent = create_agent(
    model = "gpt-5.4-mini",
    system_prompt = answer_creation_prompt
)

@tool
async def call_search_web_agent(x:str):
    """call search_web_agent when to find badminton related information from the web"""
    try:
        response = await search_web_agent.ainvoke({"messages":[HumanMessage(content=f"Search for information related to {x}")]})
        return {"messages": [AIMessage(content=response["messages"][-1].content)]}
    except Exception as e:
        return f"search_web agent failed: {str(e)}"

@tool
async def call_database_agent(x:str):
    """call database_agent when you want to find information related to player information like country, birthdate, height and highest ranking"""
    try:
        response = await database_agent.ainvoke({"messages":[HumanMessage(content=f"Search for information related to {x}")]})
        return {"messages": [AIMessage(content=response["messages"][-1].content)]}
    except Exception as e:
        return f"Database agent failed: {str(e)}"

@tool
async def call_mcp_agent(x:str):
    """call the mcp agent to find information related to badminton competition"""
    try:
        response = await mcp_agent.ainvoke({"messages":[HumanMessage(content=f"Search for information related to {x}")]})
        return {"messages": [AIMessage(content=response["messages"][-1].content)]}
    except Exception as e:
            return f"MCP agent failed: {str(e)}"

@tool
async def call_answer_creation_agent(x:str):
    """Calling answer creation agent to form the answer"""
    try:
        response = await answer_creation_agent.ainvoke({"messages":[HumanMessage(content=x)]})
        return response
    except Exception as e:
            return f"Answer creation agent failed: {str(e)}"

manager_agent = create_agent(
    model = "gpt-5.4-mini",
    tools = [call_answer_creation_agent,call_mcp_agent,call_database_agent,call_search_web_agent],
    system_prompt = manager_prompt,
    middleware = [
        SummarizationMiddleware (
        model= "gpt-5.4-nano",
        trigger = ("tokens",1000),
        keep= ("messages",20)
    )],
    checkpointer = InMemorySaver()
)

"Establish Connection to UI"
@app.get("/")
def root():
    return {"status": "ShuttleInfo AI is running ", "storage": "SQLite (ShuttleInfo_AI.db)"}

@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="OpenAI API key not set.")

    config = {"configurable": {"thread_id": req.thread_id}}

    save_chat(req.thread_id, req.message[:30])
    save_message(req.thread_id, "user", req.message)

    full_reply: list[str] = []

    async def generate():
        try:
            async for chunk in manager_agent.astream(
                {"messages": [HumanMessage(req.message)]},
                config=config,
                stream_mode="values"  
            ):
                pass  
            
            final_answer = chunk["messages"][-1].content

            for word in final_answer.split(" "):
                token = word + " "
                full_reply.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"
                await asyncio.sleep(0.03) 

            save_message(req.thread_id, "assistant", "".join(full_reply).strip())
            yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

@app.get("/api/chats")
def get_chats():
    return get_all_chats()

@app.get("/api/chats/{thread_id}/messages")
def get_chat_messages(thread_id: str):
    return get_messages_by_thread(thread_id)

@app.delete("/api/chats/{thread_id}")
def delete_chat(thread_id: str):
    delete_chat_by_thread(thread_id)
    return {"status": "deleted", "thread_id": thread_id}
