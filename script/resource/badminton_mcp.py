from dotenv import load_dotenv
import requests
import os
from mcp.server.fastmcp import FastMCP
from requests import get


load_dotenv()
api_key = os.getenv("SPORTRADAR_API_KEY")
mcp = FastMCP("Badminton_MCP_server")

competition_url = "https://api.sportradar.com/badminton/trial/v2/en/competitions.json"

def get_sportrader_info(url):
    
    headers = {
        "accept": "application/json",
        "x-api-key": api_key
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return {"error": "Failed to fetch competition data"}
    
    data = response.json()
    return data

@mcp.tool()
def get_competitions_id():
    """
    Get a list of all available competitions from Sportradar. The information provided from this are, Unique ID for a competition, tournament_name,Unique parent ID for a 
    competition, Type of a competition (ex: single, doubles), Gender for a competition
    """
    result = []
    
    data = get_sportrader_info(competition_url)
    competitions = data.get("competitions",[])
    
    for comp in competitions:
        comp_id= comp.get("id")
        number_id = comp_id.split(":")[-1]  
        comp_json = {
            "competition_id": number_id,
            "name": comp.get("name"),
            "parent_id": comp.get("parent_id"),
            "type": comp.get("type"),
            "gender": comp.get("gender")
        }
        result.append(comp_json)
    
    return result

@mcp.tool()
def get_competition_info(id):
    """
    Get the name, id, type and gender for a given competition from Sportradar.
    """
    try: 
        info_url =f"https://api.sportradar.com/badminton/trial/v2/en/competitions/sr%3Acompetition%{id}/info.json"
        data = get_sportrader_info(info_url)
        info = data.get("competition", {})

        return {
            "competition_id": info.get("id"),
            "name": info.get("name"),
            "type": info.get("type"),
            "gender": info.get("gender"),
            "category": info.get("category", {}).get("name")
        }
    except Exception as e:
        return {"error": f"Error: {str(e)}"}

@mcp.tool()
def get_historical_seasons(id):
    """
    Get historical season information for a given competition from Sportradar
    """
    season_url = f"https://api.sportradar.com/badminton/trial/v2/en/competitions/sr%3Acompetition%{id}/seasons.json"
    data = get_sportrader_info(season_url)
    season = data.get("seasons",[])
    result = []
    try:
        for items in season:
            result.append({
                "season_id": items.get("id"),
                "name": items.get("name"),
                "start_date": items.get("start_date"),
                "end_date": items.get("end_date"),
                "year": items.get("year"),
                "competition_id": items.get("competition_id")
            })
    except Exception as e:
        return {"error": f"Error: {str(e)}"}

@mcp.prompt()
def prompt():
    """
    Analyze badminton compeititon information from the sportradar api
    """
    return"""
    You are a assistant that will answer user questions regarding badminton competition
    
    You can use the following tools/resource to answer th user questions:
    get_competitions_id: Retreive a list of competitions inclduing their unique ID
    get_competitions_info (require id): Retrieves detailed information about a specific competition, given its competition_id.
    get_historical_seasons (require id): Get historical season information for a given competition
    
    Rules:
    1. Always use get_competitions_id tool first to retrieve competition IDs before calling any other tool. 
    2. For questions about historical seasons:
        - First retreive the correct "competition_id" using the get_competition tool
        - Then input the competition_id into the get_historical_seasons tool
        - Do not use get_competitions_info
    3.  For questions about a specific competition’s details (name, type, gender):
        - First retreive the correct "competition_id" using the get_competition tool
        - Then input the competition_id into the get_competitions_info tool
        - Do not use get_historical_seasons
    4.  Do not guess IDs or data 
    5. Follow the workflow strictly: **get_competitions_id → get_competition_info / get_historical_seasons**.  
    6. Do not retry the API search if API does not return any information or return NULL .
    
    Whenever you have to answer a question, you have to use the get_competitions_id tool first. If the user ask for historical season information, retrieve the 
    competition_id from get_competitions_id tool, then feed into the tool
    
    """

if __name__ =="__main__":
    mcp.run(transport="stdio")