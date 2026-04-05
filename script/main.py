from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel
import os
import json
from langchain.messages import HumanMessage
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse 
from contextlib import asynccontextmanager
from resource.chat_database import start_database , save_chat , save_message , get_all_chats , get_messages_by_thread ,delete_chat_by_thread
from agents.manager_agent import create_manager_agent
from agents import subagent
from langchain.agents import create_agent

load_dotenv()
manager_agent = None

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
    global mcp_prompt, mcp_tools, manager_agent
    mcp_prompt, mcp_tools = await start_MCP()
    subagent.mcp_agent = create_agent(model="gpt-5.4-nano", tools=mcp_tools, system_prompt=mcp_prompt)
    start_database()
    manager_agent = create_manager_agent()
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "shuttle-info-ai.vercel.app"
    ],
    allow_methods=["*"],
    allow_headers=["*"],
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

    save_chat(req.thread_id, req.message)
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
