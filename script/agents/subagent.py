from dotenv import load_dotenv
from typing import List, Any, Optional, Dict
from tavily import TavilyClient
import os
import wikipedia as wk
from langchain.agents import create_agent
from langchain.messages import HumanMessage,AIMessage
from resource.agent_prompt import get_agent_system_prompt
from langchain_openai import OpenAIEmbeddings
from langchain.tools import tool
from pydantic import BaseModel, Field, model_validator
import psycopg2
from pgvector.psycopg2 import register_vector
import asyncio

load_dotenv()
search_engine = TavilyClient()

embeddings_model = OpenAIEmbeddings()

SINGLES_ALLOWED_FIELDS = {
    "name":     "name",
    "country":  "country",
    "category": "category",
    "rank":     "rank",
    "points":   "points"
}

DOUBLES_ALLOWED_FIELDS = {
    "name":  "dp.name",
    "country":      "dp.country",
    "pair_name":    "p.pair_name",
    "category":     "p.category",
    "rank":         "p.rank",
    "points":       "p.points"
}

def get_connection():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
    return conn

class SinglesSearchQuery(BaseModel):
    category:   Optional[str]   = Field(None)
    name:       Optional[str]   = Field(None)
    country:    Optional[str]   = Field(None)
    rank:       Optional[int]   = Field(None)
    rank_min:   Optional[int]   = Field(None)
    rank_max:   Optional[int]   = Field(None)
    points:     Optional[int]   = Field(None)
    limit:      int             = Field(6, description="Number of results to return, max 20")

class DoublesSearchQuery(BaseModel):
    category:       Optional[str]   = Field(None)
    name:           Optional[str]   = Field(None)
    pair_name:      Optional[str]   = Field(None)
    country:        Optional[str]   = Field(None)
    rank:           Optional[int]   = Field(None)
    rank_min:       Optional[int]   = Field(None)
    rank_max:       Optional[int]   = Field(None)
    points:         Optional[int]   = Field(None)  
    limit:          int             = Field(6, description="Number of results to return, max 20")

class ProfileSearchQuery(BaseModel):
    query:          str           = Field(...,  description="Natural language question e.g. 'Olympic gold medal'")
    name:           Optional[str] = Field(None, description="Filter by player name")
    content_type:   Optional[str] = Field(None, description="'biography', 'career', or 'achievement'")
    k:              int           = Field(6,    description="Number of results to return, max 20")
        
    @model_validator(mode="before")
    @classmethod
    def handle_string_input(cls, values: Any) -> Any:
        if isinstance(values, str):
            return {"query": values}
        return values
    
def search_singles_sync(query: SinglesSearchQuery) -> str:
    try:
        conn = get_connection()
        cursor = conn.cursor()

        selected = list(SINGLES_ALLOWED_FIELDS.values()) 

        sql = f"""
            SELECT {', '.join(selected)}
            FROM badminton.singles_players
            WHERE 1=1
        """
        params = []

        if query.category:  sql += " AND category = %s";    params.append(query.category)
        if query.country:   sql += " AND country = %s";     params.append(query.country.upper())
        if query.rank:      sql += " AND rank = %s";        params.append(query.rank)
        if query.rank_min:  sql += " AND rank >= %s";       params.append(query.rank_min)
        if query.rank_max:  sql += " AND rank <= %s";       params.append(query.rank_max)
        if query.name:
            clean_name = query.name.replace(",", "").strip()
            name_parts = clean_name.split()
            part_conditions = " OR ".join(["name ILIKE %s"] * len(name_parts))
            sql += f" AND ({part_conditions})"
            params.extend(f"%{part}%" for part in name_parts)
    
        sql += " ORDER BY rank ASC LIMIT %s"
        params.append(min(query.limit, 20))

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return "No singles players found."

        output = []
        for row in rows:
            row_data = dict(zip(SINGLES_ALLOWED_FIELDS.keys(), row))
            output.append(" | ".join(f"{k}: {v}" for k, v in row_data.items()))
        return "\n".join(output)
    except Exception as e:
        return f"Error searching singles: {str(e)}"

def search_doubles_sync(query: DoublesSearchQuery) -> str:
    """This function is use to search information regarding men double badminton players, women double badminton players and mixed double badminton players"""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        selected = list(DOUBLES_ALLOWED_FIELDS.values()) 
        
        sql = f"""
            SELECT {', '.join(selected)}
            FROM badminton.doubles_players dp
            JOIN badminton.doubles_pairs p ON dp.pair_id = p.pair_id
            WHERE 1=1
        """
        params = []

        if query.category:      sql += " AND p.category = %s";         params.append(query.category)
        if query.pair_name:     sql += " AND p.pair_name ILIKE %s";    params.append(f"%{query.pair_name}%")
        if query.country:       sql += " AND dp.country = %s";         params.append(query.country.upper())
        if query.rank:          sql += " AND p.rank = %s";             params.append(query.rank)
        if query.rank_min:      sql += " AND p.rank >= %s";            params.append(query.rank_min)
        if query.rank_max:      sql += " AND p.rank <= %s";            params.append(query.rank_max)
        if query.name:
            clean_name = query.name.replace(",", "").strip()
            name_parts = clean_name.split()
            part_conditions = " OR ".join(["name ILIKE %s"] * len(name_parts))
            sql += f" AND ({part_conditions})"
            params.extend(f"%{part}%" for part in name_parts)

        sql += " ORDER BY p.rank ASC LIMIT %s"
        params.append(min(query.limit, 20))

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return "No doubles players found."

        output = []
        for row in rows:
            row_data = dict(zip(DOUBLES_ALLOWED_FIELDS.keys(), row))
            output.append(" | ".join(f"{k}: {v}" for k, v in row_data.items()))
        return "\n".join(output)
    except Exception as e:
        return f"Error searching doubles: {str(e)}"

def search_profile_sync(query: ProfileSearchQuery) -> str:
    """This function is use to find the profile of a specific player, including biography, career and achievements"""
    try:
        conn = get_connection()
        register_vector(conn)
        cursor = conn.cursor()

        query_vector = embeddings_model.embed_query(query.query)

        sql = """
            SELECT name, content_type, content,
                1 - (embedding <=> %s::vector) AS similarity
            FROM badminton.player_profiles
            WHERE 1=1
        """
        params = [query_vector]

        if query.content_type:  sql += " AND content_type = %s";    params.append(query.content_type)
        if query.name:
            clean_name = query.name.replace(",", "").strip()
            name_parts = clean_name.split()
            part_conditions = " OR ".join(["name ILIKE %s"] * len(name_parts))
            sql += f" AND ({part_conditions})"
            params.extend(f"%{part}%" for part in name_parts)
    
        sql += " ORDER BY similarity DESC LIMIT %s"
        params.append(min(query.k, 20))

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return "No profile information found."

        output = []
        for name_, content_type_, content_, similarity_ in rows:
            output.append(
                f"[{content_type_.upper()}] {name_} (similarity: {similarity_:.2f}):\n{content_}\n"
            )
        return "\n".join(output)
    except Exception as e:
        return f"Error searching profiles: {str(e)}"

@tool
async def search_singles(query: SinglesSearchQuery) -> str:
    """This function is use to search information regarding men single badminton player and women single badminton player"""
    return await asyncio.to_thread(search_singles_sync, query)

@tool
async def search_doubles(query: DoublesSearchQuery) -> str:
    """This function is use to search information regarding men double badminton players, women double badminton players and mixed double badminton players"""
    return await asyncio.to_thread(search_doubles_sync, query)

@tool
async def search_profile(query: ProfileSearchQuery) -> str:
    """This function is use to find the profile of a specific player, including biography, career and achievements"""
    return await asyncio.to_thread(search_profile_sync, query)

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


search_web_prompt, database_prompt, answer_creation_prompt, manager_prompt = get_agent_system_prompt()

search_web_agent = create_agent(
    model="gpt-5.4-nano",
    tools=[search_wikipedia, search_web],
    system_prompt=search_web_prompt
)

database_agent = create_agent(
    model="gpt-5.4-nano",
    tools=[search_singles,search_doubles,search_profile],
    system_prompt=database_prompt
)

mcp_agent = None

answer_creation_agent = create_agent(
    model="gpt-5.4-nano",
    system_prompt=answer_creation_prompt
)

@tool
async def call_search_web_agent(x: str):
    """call search_web_agent to find badminton info from the web"""
    response = await search_web_agent.ainvoke({"messages": [HumanMessage(content=f"Search for {x}")]})
    return {"messages": [AIMessage(content=response["messages"][-1].content)]}

@tool
async def call_database_agent(x: str):
    """call database for player info like country, birthdate, height"""
    response = await database_agent.ainvoke({"messages": [HumanMessage(content=f"Search for {x}")]})
    return {"messages": [AIMessage(content=response["messages"][-1].content)]}

@tool
async def call_mcp_agent(x: str):
    """call mcp agent for badminton competition info"""
    response = await mcp_agent.ainvoke({"messages": [HumanMessage(content=f"Search for {x}")]})
    return {"messages": [AIMessage(content=response["messages"][-1].content)]}

@tool
async def call_answer_creation_agent(x: str):
    """call answer creation agent to form the final answer"""
    return await answer_creation_agent.ainvoke({"messages": [HumanMessage(content=x)]})