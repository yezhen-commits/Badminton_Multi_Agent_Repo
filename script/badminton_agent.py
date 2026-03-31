from dotenv import load_dotenv
from pprint import pprint
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain.tools import tool
from typing import List, Any, Optional
from pydantic import BaseModel
from tavily import TavilyClient
import wikipedia as wk
from typing import Dict, Any, List
from langchain.agents import create_agent
from langchain.messages import HumanMessage,AIMessage
from langchain.agents.middleware import SummarizationMiddleware
import asyncio

class QueryResult(BaseModel):
    success: bool
    data: Optional[List[Any]] = None
    error: Optional[str] = None

block_word_list = ["drop", "delete", "update", "insert", "alter"]

load_dotenv()

mysql_uri = "mysql+mysqlconnector://root:yezhen0100@localhost:3306/badminton_player_database"
db = SQLDatabase.from_uri(mysql_uri)
                          
search_engine = TavilyClient()

"""System prompt for agents"""
search_web_prompt = """
    You are an agent that have access to 2 tools, search_wikipedia and search_web here are the rules to use the tools:
    Rueles:
    1. For general badminton questions:
       - Always use search_wikipedia first
       - Use search_web if search_wikipedia either does not provide enough informaiton or search_wikipedia does not have the information or the user asks for more details
       
    2. For product or specification questions such as badminton rackets, shuttlecock or shoes
       - Use search_web only.
       - Do not use search_wikipedia
    
    3. Always follow these rules
    
"""

database_prompt = """
You are a agent that has access to `badminton_player_database` and you are responsible to retrieve information from the database.

Database structure:
1. men_single:
- id, name, country, birth_date, height, highest_ranking 

2. women_single:
- same structure as men_single

3.men_double:
- player1_name, player1_country, player1_birth_date, player1_height,player2_name, player2_country, player2_birth_date, player2_height,highest_ranking

4. women_double:
- same structure as men_double

5. mixed_double:
- same structure as men_double

Rules:
1. Only read data. 
2. Only query tables that are relevant to the user's question.
"""

answer_creation_prompt = """
You are a agent that is responsible for creating a proper answer from the information provided by the database_agent,mcp_agent and search_web agent
When given data or information, output it in a **point form list** where each point uses the **topic or field name** as the label. Do NOT use generic placeholder "Item 1, Item 2". 
You do  not have any access to any tools
Example:

Question: "Provide a list of badminton players and their age"

Format the answer like:

name: [player name]
age: [player age]

Always replace 'name' and 'age' with the appropriate field/topic from the question.

"""

manager_prompt = """
You are a manager agent responsible for orchestrating tasks across multiple specialized agents.

You DO NOT answer user questions directly. Your role is to:
1. Understand the user questions
2. Decide which agent(s) to call
3. Collect results from those agents
4. Pass the final collected information to the answer_creation_agent

You have access to the following agents:

1. database_agent  
   - Provides badminton player information  
   - Includes: name, country, birth_date, height, highest_ranking  

2. mcp_agent  
   - Provides badminton competition information from Sportradar  
   - Includes: competition details, competition_id, seasons, categories  

3. search_web_agent  
   - Provides general badminton-related information from web and Wikipedia  

4. answer_creation_agent  
   - Responsible for generating the final structured and well-written answer  

---

Routing Rules:

1. Player-related queries:
   - If the user asks about player details (e.g., country, birth date, height, peak rankings)
   → Call **database_agent**

2. Competition-related queries:
   - If the user asks about badminton competitions, tournaments, or seasons
   → Call **mcp_agent**

3. General badminton queries:
   - For any other badminton-related question (rules, equipment, history, etc.) other than badminton competitions, tournaments, seasons and badminton player information like country, birth date, height, peak rankings 
   → Call **search_web_agent**

---

Fallback Rules (VERY IMPORTANT):
4. If **database_agent** returns:
   - no data
   - empty result
   - or an error  
   → Call **search_web_agent** as fallback

5. If **mcp_agent** returns:
   - no data
   - empty result
   - or an error  
   → Call **search_web_agent** as fallback
---

Final Step (MANDATORY):

6. After collecting all relevant information from the selected agent(s):
   - DO NOT generate the final answer yourself
   - ALWAYS pass the collected data to **answer_creation_agent**
---

7. After collecting the answer from answer_creation_agent, take the answer generated from answer_creation_agent as the output

Behavior Rules:

- Do NOT skip agent calls
- Do NOT fabricate information
- Do NOT answer directly
- Always follow routing rules strictly
- Ensure the final response comes ONLY from answer_creation_agent

"""
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

    return mcp_prompt,mcp_tools

mcp_prompt, mcp_tools = asyncio.run(start_MCP())

@tool 
def query_mysql(query: str): 
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
def search_web(query:str)->Dict[str,Any]:
    """
    Use this tool to search the web for information 
    """
    
    return search_engine.search(query)

@tool
def search_wikipedia(query: str) -> Dict[str, Any]:
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
    model = "gpt-5-nano",
    tools = [search_wikipedia,search_web],
    system_prompt = search_web_prompt
)

database_agent = create_agent(
    model= "gpt-5-nano",
    tools = [query_mysql],
    system_prompt = database_prompt
)

mcp_agent =  create_agent(
    model = "gpt-5-nano",
    tools = mcp_tools,
    system_prompt = mcp_prompt
)

answer_creation_agent = create_agent(
    model = "gpt-5.4-mini",
    system_prompt = answer_creation_prompt
)

@tool
def call_search_web_agent(x:str):
    """call search_web_agent when to find badminton related information from the web"""
    response = search_web_agent.invoke({"messages":[HumanMessage(content=f"Search for information related to {x}")]})
    return {"messages": [AIMessage(content=response["messages"][-1].content)]}

@tool
def call_database_agent(x:str):
    """call database_agent when you want to find information related to player information like country, birthdate, height and highest ranking"""
    response = database_agent.invoke({"messages":[HumanMessage(content=f"Search for information related to {x}")]})
    return {"messages": [AIMessage(content=response["messages"][-1].content)]}

@tool
async def call_mcp_agent(x:str):
    """call the mcp agent to find information related to badminton competition"""
    response = await mcp_agent.ainvoke({"messages":[HumanMessage(content=f"Search for information related to {x}")]})
    return {"messages": [AIMessage(content=response["messages"][-1].content)]}

@tool
async def call_answer_creation_agent(x:str):
    """Calling answer creation agent to form the answer"""
    response = await answer_creation_agent.ainvoke({"messages":[HumanMessage(content=x)]})
    return response

manager_agent = create_agent(
    model = "gpt-5.4-mini",
    tools = [call_answer_creation_agent,call_mcp_agent,call_database_agent,call_search_web_agent],
    system_prompt = manager_prompt,
    middleware = [
        SummarizationMiddleware (
        model= "gpt-5.4-nano",
        trigger = ("tokens",1000),
        keep= ("messages",20)
    )]
)
