from ..utils.console import console
import requests
from pathlib import Path
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from ..internal.llm import llm_completion_async
import asyncio
import time


def _get_page_content(url):
    """Extract clean content from a webpage."""
    start_time = time.perf_counter()
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Eliminar elementos no deseados
        for element in soup(['script', 'style', 'header', 'footer', 'nav', 'meta', 'link']):
            element.decompose()
        
        # Extraer contenido del body
        body = soup.body
        if body:
            text = body.get_text(separator=' ', strip=True)
            duration = time.perf_counter() - start_time
            console.info("Web Scraping", f"Fetched and cleaned content from {url} in {duration:.2f}s")
            return ' '.join(text.split())
        return None
    except Exception as e:
        console.error("Web Scraping", f"Error fetching content from {url}: {str(e)}")
        return None

def _search_web(task_memory, user_input, task_id, fast_search):
    """Search the web using Brave API and return structured results."""
    start_time = time.perf_counter()
    
    # Load API key
    env_path = Path(__file__).resolve().parent.parent / '.env'
    load_dotenv(dotenv_path=env_path)
    brave_key = os.getenv('BRAVE_KEY')

    # Make search request
    try:
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "x-subscription-token": brave_key
            },
            params={
                "q": user_input,
                "count": 1 if fast_search else 5
            }
        ).json()
    except Exception as e:
        console.error("Web Search", f"API request failed: {str(e)}")
        return []

    # Process results
    search_results = []
    if 'web' in response and 'results' in response['web']:
        results = response['web']['results']
        for result in results:
            content = _get_page_content(result['url'])
            search_results.append({
                'title': result['title'],
                'url': result['url'],
                'description': result['description'],
                'content': content
            })
    
    duration = time.perf_counter() - start_time
    console.success("Web Search", f"Completed search for '{user_input}' in {duration:.2f}s")
    return search_results


async def _search_and_summarize(task_memory: list, query: str, task_id: int = 1, fast_search: bool = True) -> str:
    """Search the web and generate a summary of the results using LLM."""
    start_time = time.perf_counter()
    LIMIT_LLM_CONTENT = 5000
    
    console.tool("Web Search", "Brave API - Data extracting")
    results = _search_web(task_memory=task_memory, user_input=query, task_id=task_id, fast_search=fast_search)
    
    if not results:
        console.error("Web Search", "No results found or API error")
        return "No results found"
    else:
        console.success("Web Search", "Data extracted correctly")
    
    console.tool("Web Search", "Preparing LLM summary")
    content_to_summarize = f"Search Query: {query}\n\n"
    for result in results:
        content_to_summarize += f"Title: {result['title']}\n"
        content_to_summarize += f"Content: {result['content'][:LIMIT_LLM_CONTENT] if result['content'] else 'No content available'}\n\n"
    
    prompt = f"""Please provide a concise summary of the following web search results:
    {content_to_summarize}
    Provide a clear and informative summary that captures the key information from these results."""
    
    llm_start = time.perf_counter()
    summary, _ = await llm_completion_async(
        model="gemini-2.5-flash-lite",
        prompt=prompt,
        system_message=f"You are a helpful assistant that summarizes web search results clearly and concisely. The starting request was {query}, compose your summary based on that",
        max_tokens=500
    )
    llm_duration = time.perf_counter() - llm_start
    total_duration = time.perf_counter() - start_time
    console.info("LLM Summarization", f"Completed in {llm_duration:.2f}s, total function time {total_duration:.2f}s")

    return summary

async def web_search(task_memory, text, task_id=1, fast_search=True):
    """Wrapper around `search_web` that extracts the user search query from a text using LLM."""
    start_time = time.perf_counter()
    console.tool("Web Search", "LLM Query inference - Extracting search query")

    # Step 1: Extract user_input from text
    prompt = f"""
    Extract the browser search query from the following text. 
    Provide only the query string without extra explanation.

    Text: \"\"\"{text}\"\"\"
    """

    llm_start = time.perf_counter()
    user_input, _ = await llm_completion_async(
        model="gemini-2.5-flash-lite",
        prompt=prompt,
        system_message="You are an assistant that extracts the user's search query from any given text.",
        max_tokens=100
    )
    llm_duration = time.perf_counter() - llm_start
    user_input = user_input.strip()
    console.info("Web Search", f"Inferred search query: '{user_input}' in {llm_duration:.2f}s")
  
    console.tool("Web Search", "Proceeding to web search")
    results = await _search_and_summarize(task_memory=task_memory, query=user_input, task_id=task_id, fast_search=fast_search)
    
    total_duration = time.perf_counter() - start_time
    console.info("Web Search", f"Total web_search execution time: {total_duration:.2f}s")
    return results
