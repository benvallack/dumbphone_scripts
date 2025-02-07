#!/usr/bin/env python3
from bs4 import BeautifulSoup
import re
import time
import json 
import requests
import openai
import subprocess
import sqlite3
import os
import shutil
from datetime import datetime
import os
import sys


# -------------------------------
# Configuration and API Keys
# -------------------------------


# Google Directions API
GOOGLE_DIRECTIONS_API_KEY = ""

# Google Custom Search API (for web search)
GOOGLE_SEARCH_API_KEY = ""
GOOGLE_SEARCH_ENGINE_ID = ""  # Your Custom Search Engine ID

# OpenWeatherMap API
OPENWEATHER_API_KEY = ""
OPENWEATHER_ENDPOINT = "http://api.openweathermap.org/data/3.0/onecall"

# OpenAI API configuration
OPENAI_API_KEY = ""  # Replace with your OpenAI API key
openai.api_key = OPENAI_API_KEY

# BulkSMS API configuration (adjust based on BulkSMS documentation)
BULKSMS_USERNAME = ""
BULKSMS_PASSWORD = ""
BULKSMS_ENDPOINT = "https://api.bulksms.com/v1/messages"  # Verify the endpoint in your BulkSMS account docs


# Your phone number (as stored in Apple Messages handles)
MY_NUMBER = "+44123456789"  # Replace with your dumphone number


# File to persist the last processed message date (an integer, as stored in the Messages DB)
LAST_DATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_date.txt")


# -------------------------------
# Functions to handle the lock to make sure a slow process doesn't result in the script overlapping.
# -------------------------------

LOCK_FILE = "/tmp/autresponder.lock"  # Adjust path as needed

def check_lock():
    """Check if another instance is already running."""
    if os.path.exists(LOCK_FILE):
        print("Script is already running. Exiting.")
        sys.exit(1)
    else:
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))

def remove_lock():
    """Remove lock file on exit."""
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)

# -------------------------------
# Persistence Helpers
# -------------------------------

def load_last_date():
    try:
        with open(LAST_DATE_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 0

def save_last_date(last_date):
    with open(LAST_DATE_FILE, "w") as f:
        f.write(str(last_date))


def chatgpt_fix(text,orig):
    prompt = f"""Provide basic fixes and ensure sting is less than 160 characters. Return only the fixed text. The text should be a response to the following question: {orig}"""
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ]
        )
        response = response.choices[0].message.content
        return response
    except Exception as e:
        print("Error using chatgpt_fix", e)
        return "Error using chatgpt_fix"

# -------------------------------
# Local Ollama Summarisation Helper
# -------------------------------
        
def ollama_fix(text):
    """
    Uses your local Ollama model to summarize the given text.
    Assumes that the Ollama CLI is installed and configured, and that 'your_local_model'
    is the name of the model to use for summarisation.
    """
    model_name = "llama3.2"  # Replace with your local model name in Ollama.
    # Create a summarisation prompt.
    prompt = f"Improve, return only the improved text: {text}"
    try:
        result = subprocess.check_output(["ollama", "run", model_name, prompt],
                                         stderr=subprocess.STDOUT)
        return result.decode("utf-8").strip()
    except Exception as e:
        return f"Error running Ollama model: {e}"

# -------------------------------
# Local Ollama Summarisation Helper
# -------------------------------

def ollama_summarise(text):
    """
    Uses your local Ollama model to summarize the given text.
    Assumes that the Ollama CLI is installed and configured, and that 'your_local_model'
    is the name of the model to use for summarisation.
    """
    model_name = "llama3.2"  # Replace with your local model name in Ollama.
    # Create a summarisation prompt.
    prompt = f"Summarize the following content concisely:\n\n{text}"
    try:
        result = subprocess.check_output(["ollama", "run", model_name, prompt],
                                         stderr=subprocess.STDOUT)
        return result.decode("utf-8").strip()
    except Exception as e:
        return f"Error running Ollama model: {e}"

# -------------------------------
# ChatGPT Processing Functions
# -------------------------------

def get_chatgpt(message_text):
    prompt = f"""You are a bot for providing answers. Summerize the answers to fit in 160 characters. Don't use unicode characers or formatting. """
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": message_text}
            ]
        )
        response = response.choices[0].message.content
        return response
    except Exception as e:
        print("Error using get_chatgpt", e)
        return "Error using get_chatgpt"

# -------------------------------
# Command Processing Functions
# -------------------------------

def classify_command(message_text):
    prompt = f"""You are a command classifier. Based on the following SMS command, classify the type of request.
Consider if chatgpt can provide a good anwer without web search, if so use CHATGPT, otherwise use the others.
Return exactly one word, in order of priority: OPENINGTIMES, DIRECTIONS, CHATGPT, WEATHER, EMAIL_SUMMARY, WEB_SEARCH, EMAIL_SEARCH or MESSAGES_SUMMARY.
SMS Command: "{message_text}" """
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a command classification assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        classification = response.choices[0].message.content.strip().upper()
        valid = ["OPENINGTIMES", "CHATGPT", "DIRECTIONS", "WEB_SEARCH", "WEATHER", "EMAIL_SUMMARY",  "EMAIL_SEARCH", "MESSAGES_SUMMARY"]
        if classification not in valid:
            classification = "UNKNOWN"
        return classification
    except Exception as e:
        print("Error classifying command:", e)
        return "UNKNOWN"


# -------------------------------
# 1. Query Normalization with ChatGPT
# -------------------------------
def normalize_query(query):
    """
    Uses OpenAI to convert a natural language query into a JSON object with these fields:
      - "business": the name of the business.
      - "request": either "opening" or "closing".
      - "date": the specific date in YYYY-MM-DD format for which the hours are requested.
      
    For example:
      Input: "what time does sainsburys close on boxing day"
      Output: {"business": "sainsbury's", "request": "closing", "date": "2023-12-26"}
    """
    today_date = datetime.today().strftime("%Y-%m-%d")
    prompt = f"""
Assume today's date is {today_date}. Convert the user text natural-language query into a JSON object with these fields:
- "business": the name of the business.
- "request": either "opening" or "closing" (depending on whether the query asks for opening time or closing time).
- "date": the specific date in YYYY-MM-DD format for which the hours are requested.

Automatically interpret relative terms such as "tomorrow" or holiday names like "boxing day" using today's date.

For example:
Input: "what time does sainsburys close tomorrow"
Output: {{"business": "sainsbury's", "request": "closing", "date": "2023-11-25"}}

Now convert the content:
"""
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",  # or GPT-4 if available
            messages=[
                {"role": "system", "content": prompt },
                {"role": "user", "content": query}
            ]
        )
        normalized = json.loads(response.choices[0].message.content.strip())
        return normalized
    except Exception as e:
        print("Error normalizing query:", e)
        return None

# -------------------------------
# 2. Date Conversion Helper
# -------------------------------
def date_to_google_index(date_str):
    """
    Converts a date string (YYYY-MM-DD) to a Google weekday index.
    Google Places API uses: Sunday = 0, Monday = 1, …, Saturday = 6.
    Python's datetime.weekday() returns Monday=0,...,Sunday=6.
    We convert by: google_index = (weekday + 1) % 7.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return (dt.weekday() + 1) % 7
    except Exception as e:
        print("Error converting date to weekday index:", e)
        return None
        
# -------------------------------
# 3. Google Places API Helpers
# -------------------------------
def get_place_details(business, api_key):
    """
    Uses the new Google Places Text Search API to find the candidate place,
    then calls the Place Details endpoint to retrieve the opening_hours information.

    Parameters:
        business (str): The business name or query.
        api_key (str): Your Google Places API key.

    Returns:
        tuple: (place_name, opening_hours) on success, or (None, error_message) on failure.
    """
    # --- Step 1: Use the new Text Search API (v1) ---
    textsearch_url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        # Request only the fields we need: placeId and displayName.
        "X-Goog-FieldMask": "places.id,places.displayName"
    }
    data = {
        "textQuery": business
    }
    
    response = requests.post(textsearch_url, headers=headers, json=data)
    if response.status_code != 200:
        print(f"Text Search API error: {response.status_code} {response.text}""Text Search API error: {response.status_code} {response.text}")
        return None, f"Text Search API error: {response.status_code} {response.text}"
    
    textsearch_data = response.json()
    # The new API returns a "places" array.
    if "places" not in textsearch_data or len(textsearch_data["places"]) == 0:
        return None, "Business not found."
    
    candidate = textsearch_data["places"][0]
    place_id = candidate.get("id")
    place_name = candidate.get("displayName", business)  # Fallback to input if displayName is missing.
    

    # --- Step 2: Use the new Place Details API (v1) ---
    details_url = f"https://places.googleapis.com/v1/places/{place_id}"
    details_headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        # Request the fields: id, displayName, and openingHours.
        "X-Goog-FieldMask": "*"
    }
    details_response = requests.get(details_url, headers=details_headers)
    if details_response.status_code != 200:
        return None, f"Place Details API error: {details_response.status_code} {details_response.text}"
    
    details_data = details_response.json()
    # In the new API, the opening hours may be returned under the key "openingHours"
    opening_hours = details_data.get("currentOpeningHours")
    if opening_hours is None:
        return place_name, None  # It is possible the business does not have openingHours data.
    
    return place_name, opening_hours


def get_hours_for_date(opening_hours, date_str, request_type):
    """
    Extracts the requested opening or closing time for a given date.
    
    Parameters:
        opening_hours (dict): The `currentOpeningHours` object from Google Places API.
        date_str (str): The date in YYYY-MM-DD format.
        request_type (str): Either "opening" or "closing".
    
    Returns:
        str: The formatted time (HH:MM) if found, otherwise None.
    """
    if not opening_hours or "periods" not in opening_hours:
        return None  # No valid opening hours data.
    
    try:
        # Convert YYYY-MM-DD to a weekday index (Google format: Sunday=0, Monday=1, etc.).
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        google_weekday_index = (dt.weekday() + 1) % 7  # Convert Python Monday=0 to Google Sunday=0.

        for period in opening_hours["periods"]:
            # Check if this period matches the requested date.
            open_entry = period.get("open", {})
            close_entry = period.get("close", {})

            # Ensure that 'date' exists in open/close entries.
            open_date = open_entry.get("date", {})
            close_date = close_entry.get("date", {})

            # Compare with requested date.
            open_date_str = f"{open_date.get('year')}-{open_date.get('month'):02d}-{open_date.get('day'):02d}"
            close_date_str = f"{close_date.get('year')}-{close_date.get('month'):02d}-{close_date.get('day'):02d}"

            if date_str == open_date_str or date_str == close_date_str:
                if request_type == "opening" and "hour" in open_entry:
                    return f"{open_entry['hour']:02d}:{open_entry['minute']:02d}"
                elif request_type == "closing" and "hour" in close_entry:
                    return f"{close_entry['hour']:02d}:{close_entry['minute']:02d}"
        
        return None  # No match found for the given date.

    except Exception as e:
        print("Error processing opening hours:", e)
        return None

# -------------------------------
# 4. Main Function to Get Place Hours
# -------------------------------
def get_place_hours(query, api_key):
    """
    Given a natural language query (e.g., "what time does sainsburys close on boxing day"),
    this function uses OpenAI to convert it into structured parameters and then uses the
    Google Places API to look up the business and retrieve the requested hours.
    
    Returns a summary string such as:
       "Sainsbury's closes at 21:00 on 2023-12-22."
    """
    normalized = normalize_query(query)
    if not normalized:
        return "Error processing the query."
    
    business = normalized.get("business")
    request_type = normalized.get("request")
    date_str = normalized.get("date")
    
    if not (business and request_type and date_str):
        return "Incomplete information extracted from the query."
    
    place_name, opening_hours = get_place_details(business, api_key)
    if opening_hours is None:
        return f"Could not retrieve opening hours for {business}."
    
    time_str = get_hours_for_date(opening_hours, date_str, request_type)
    place_name=place_name.get("text")
    if not time_str:
        # Now place_name should not be None because of the fallback.
        return f"Could not find {request_type} time for {place_name} on {date_str}."
    
    return f"{place_name} {request_type}s at {time_str} on {date_str}."


def get_openingtimes(message_text):
    result = chatgpt_fix(get_place_hours(message_text, GOOGLE_DIRECTIONS_API_KEY),message_text)
    return result  


def get_directions(message_text):
    """
    Extracts origin and destination from the message and calls the Google Directions API.
    Expected user text (after overall prefix removal) should be something like:
    "Directions from [origin] to [destination]"
    """
    pattern = re.compile(r'from\s+(.*?)\s+to\s+(.*)', re.IGNORECASE)
    match = pattern.search(message_text)
    if not match:
        return "Could not extract origin and destination from your command."
    origin = match.group(1).strip()
    destination = match.group(2).strip()

    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": origin,
        "destination": destination,
        "key": GOOGLE_DIRECTIONS_API_KEY
    }
    response = requests.get(url, params=params)
    # Function to clean HTML tags
    if response.status_code == 200:
        data = response.json()
        def clean_html(raw_html):
            """
            Remove HTML tags from the given string.
            """
            clean = re.compile('<.*?>')  # Regular expression to match HTML tags
            return re.sub(clean, '', raw_html)

        if data.get("status") == "OK":
            try:
                leg = data["routes"][0]["legs"][0]
                steps = leg["steps"]
                # Extract all instructions with HTML tags removed.
                all_instructions = []
                for step in steps:
                    # Extract and clean html_instructions
                    raw_instruction = step.get('html_instructions', 'No instruction available')
                    cleaned_instruction = clean_html(raw_instruction)
                    distance = step.get('distance', {}).get('text', 'Unknown distance')

                    # Append the cleaned instruction and distance to the list
                    all_instructions.append(f"{cleaned_instruction} ({distance})")


                # Combine all instructions into a single text block.
                instructions_text = "\n".join(all_instructions)
                print(instructions_text)
                prompt = f"""
                Use your knowledge of place locations and names to make these instuctions easier to understand by suggersting what locations are likely to show on road signs at each stage.
                Steps:
                {instructions_text}
                """
                print(prompt)
                # Use OpenAI to summarise the complete route directions.
                summary_response = openai.chat.completions.create(
                    model="chatgpt-4o-latest",
                    messages=[
                        {"role": "system", "content": "You are a helpful route summary assistant"},
                        {"role": "user", "content": prompt}
                    ]
                )
                summary = summary_response.choices[0].message.content.strip()
                prompt = f"""
                Take the steps and visualise the route in terms of the town names on the signs. Group steps to make a very short, logical summary that would make it very easy to follow the main route. It must be 160 characters or less. Abreviate names as needed. Where steps are only a short distance simply focus on the next large town or motorway and all those steps can be grouped. Make sure to include motorway junction numbers when leaving motorways. Consider every step in terms of geographic location and route direction to simplify the instuction. Return only the summary.
                Steps:
                {summary}
                """

                print(summary)

                summary_response = openai.chat.completions.create(
                    model="chatgpt-4o-latest",
                    messages=[
                        {"role": "system", "content": "You are a helpful route summary assistant"},
                        {"role": "user", "content": prompt}
                    ]
                )
                summary = summary_response.choices[0].message.content.strip()

                return f"{summary}"
            except Exception as e:
                return "Directions retrieved but error processing route details."
        else:
            return f"Error retrieving directions: {data.get('status', 'Unknown error')}"
    else:
        return f"Error calling directions API: {response.status_code}"

def search_web(query, count=5):
    """
    Performs a web search using the Google Custom Search API.
    """
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_SEARCH_API_KEY,
        "cx": GOOGLE_SEARCH_ENGINE_ID,
        "q": query,
        "num": count
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        print("Error with Google search:", response.status_code, response.text)
        return None

def summarise_search_results(search_results,question):
    """
    Extracts titles and snippets from search results and asks ChatGPT to summarize them.
    """
    snippets = []
    items = search_results.get("items", [])
    for item in items:
        title = item.get("title", "No Title")
        snippet = item.get("snippet", "")
        snippets.append(f"Title: {title}\nSnippet: {snippet}")
    if not snippets:
        return "No search results found."
    combined_text = "\n\n".join(snippets)
    print(combined_text)
    prompt = f"{combined_text}"
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Extract key information from the search results snippets to answer the following question, fit within 160 characters with no formatting: {question}"},
                {"role": "user", "content": prompt}
            ]
        )
        summary = response.choices[0].message.content.strip()
        return summary
    except Exception as e:
        print("Error summarizing search results:", e)
        return "Error generating summary from search results."

def perform_web_search(message_text):
    """
    Uses the entire (post-prefix) message text as the search query.
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Convert the following natural language question into a concise, keyword-rich search query suitable for a search engine. " },
                {"role": "user", "content": message_text}
            ]
        )
        query = response.choices[0].message.content.strip()
        print(query)
    except Exception as e:
        print("Error converting search phrase:", e)
        return "Error converting search"

    results = search_web(query)
    if results:
        summary = summarise_search_results(results,message_text)
        return summary
    else:
        return "Error performing web search."

def get_weather(message_text,api_key):
    """
    Extracts the location from the message text and calls the OpenWeatherMap API.
    Expected user text might be like "What's the weather in [Location]?" or "Weather in [Location]"
    """
    prompt = "Extract the location from this string, return only the location:"
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": message_text }
            ]
        )
        business = response.choices[0].message.content
        print(f" location extracted: {business}")
    except Exception as e:
        print("Error using location extraction", e)
        return "Error using location extraction"

    # --- Step 1: Use the new Text Search API (v1) ---
    textsearch_url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        # Request only the fields we need: placeId and displayName.
        "X-Goog-FieldMask": "places.id,places.location"
    }
    data = {
        "textQuery": business
    }
    
    response = requests.post(textsearch_url, headers=headers, json=data)
    if response.status_code != 200:
        print(f"Text Search API error: {response.status_code} {response.text}""Text Search API error: {response.status_code} {response.text}")
        return None, f"Text Search API error: {response.status_code} {response.text}"
    
    textsearch_data = response.json()
    print(textsearch_data)
    # The new API returns a "places" array.
    if "places" not in textsearch_data or len(textsearch_data["places"]) == 0:
        return None, "Business not found."
    
    candidate = textsearch_data["places"][0]
    place_id = candidate.get("location")
    lat = place_id.get("latitude")
    lng = place_id.get("longitude")
    try:

        weather_url = "https://api.openweathermap.org/data/3.0/onecall"
        params = {
            "lat": lat,
            "lon": lng,
            "units": "metric",
            "appid": OPENWEATHER_API_KEY
        }
        response = requests.get(weather_url, params=params)
        if response.status_code != 200:
            print('weather api error')
            return f"OpenWeatherMap API error: {response.status_code} {response.text}"

        weather_data = response.json()

    except Exception as e:
        print('error getting weather')
        return f"Error fetching weather data: {e}"

    prompt = f"""
    Consider this message: {message_text}'. 
    Establish the requested time frame to work out which forcast is best to use. 
    i.e if no time period is in the message, return 'minutely' to retun the next hour forcast. 
    If it's something like 'today', 'later', or 'afternoon' return 'hourly'. 
    If a specific day is mentioned, use 'daily'. Return only 'minutely', 'hourly' or 'daily'.
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are to extract time periods from a reqest for weather report. Return only a single word respons: 'minutel', 'hourly' or 'daily'"},
                {"role": "user", "content": prompt }
            ]
        )
        resolution = response.choices[0].message.content

        print(f"resolution {resolution}")
    except Exception as e:
        print("Error generating weather summary", e)
        return "Error generating weather summary"

    if resolution=="minutely":
        prompt = f"""
            Summarize the current conditions and look at the minutely data in 'specific forcast' to indicate if/when it might rain.
            Use 'feels_like' when describing temps. Don't show exact wind speeds, just a language summary.
            Units supplied are metric.
            """
    if resolution=="hourly":
        prompt = f"""
            Use the question '{message_text}' to provide a relevant weather summary. 
            Use 'feels_like' when describing temps. Don't show exact wind speeds, just a language summary.
            'specific forcast' contains hourly data. Cross reference with the time period in the question. Look for changes in conditions in particular.  
            Units supplied are metric.
            """
    if resolution=="daily":
        prompt = f"""
            Use the question '{message_text}' to provide a relevant weather summary . 
            Use 'feels_like' when describing temps. Don't show exact wind speeds, just a language summary.
            'specific forcast' contains daily data weather data with timestamps in the 'dt' property.
            Find the correct day using 'dt' and then provide a weather report.
            Units supplied are metric.
            """
    try:
        response = openai.chat.completions.create(
            model="chatgpt-4o-latest",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "specific forcast:" + json.dumps(weather_data[resolution]) + " current condtitions: " + json.dumps(weather_data['current'])  }
            ]
        )
        weather = response.choices[0].message.content
    except Exception as e:
        print("Error generating weather summary", e)
        return "Error generating weather summary"

    try:
        response = openai.chat.completions.create(
            model="chatgpt-4o-latest",
            messages=[
                {"role": "system", "content": """
                 Make sure this reads concisely and fits within 160 characters. 
                Use "'C" instead of º symbols. Remove the day/time and place name. 
                 Before replying, check it fits in 160 characters and shorten if needed.
                 It MUST fit within 160 characters."""},
                {"role": "user", "content": weather}
            ]
        )
        weather = response.choices[0].message.content
        return weather
    except Exception as e:
        print("Error generating weather summary", e)
        return "Error generating weather summary"

# New Helpers for "Lookup" commands using last_date
# ----------

def remove_html(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text(separator="\n").strip()

def search_emails(message_text):

    prompt = f"""
    Consider this message: {message_text}'. 
    Extract the search term and the question. The user will be posing a search keyword to first search emails, then will include instructions on what to do with the emails.
    Return json with two properties: 'keyword' and 'task'
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are to extract 'keyword' and 'task'. Respond **only** with valid JSON in this format: {\"keyword\": \"value\", \"task\": \"value\"}"},
                {"role": "user", "content": prompt }
            ]
        )
        out = response.choices[0].message.content
        print(out)

        # Parse JSON
        extracted_data = json.loads(out)

        # Access 'keyword' and 'task'
        keyword = extracted_data.get("keyword", "No keyword found")
        task = extracted_data.get("task", "No task found")

        print(f"keyword and task {keyword} {task}")
    except Exception as e:
        print("Error extracting keyword and task", e)
        return "Error extracting keyword and task"

    applescript = f'''
    tell application "Mail"
    set searchResults to ""
    set searchTerm to "{keyword}"

    -- Get all inbox messages
    set inboxMessages to messages of inbox
    repeat with msg in inboxMessages
        set msgSubject to subject of msg
        set msgSender to sender of msg
        set msgDate to date received of msg
        set msgBody to content of msg  -- Get full email content (HTML or plain text)

        -- Search for the keyword in subject or body
        if msgSubject contains searchTerm or msgBody contains searchTerm then
            set searchResults to searchResults & "Subject: " & msgSubject & ", Sender: " & msgSender & ", Date: " & (msgDate as string) & "
Body: " & msgBody & "

"
        end if
    end repeat

    return searchResults
end tell

    '''
    print(applescript)
    process = subprocess.Popen(["osascript", "-e", applescript],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    out, err = process.communicate()
    if err and err.strip():
        return f"Error: {err.decode('utf-8')}"
    unread = out.decode("utf-8").strip()
    plain_text = remove_html(unread)
    print(plain_text)
    print("done search")
    try:
        model_name = "llama3.2"  # Replace with your local model name in Ollama.
        prompt = f"Look at these emails and respond with the result to this task: {task}. Return just the result of the task. If no obvious result just respond with 'Unable to find' "
        # Create a summarisation prompt.
        try:
            result = subprocess.check_output(["ollama", "run", model_name, prompt + "Emails: " + plain_text],
            stderr=subprocess.STDOUT)
            print(result.decode("utf-8").strip())
            return result.decode("utf-8").strip()
        except Exception as e:
            return f"Error running Ollama model: {e}"
    except Exception as e:
        print("Error using email search", e)
        return "Error using email search"

def summarize_unread_emails(last_date):
    """
    Retrieves new (unread) emails from Apple Mail whose 'date sent' is later than the given last_date.
    The last_date (an integer from the Messages DB) is assumed to be in Mac Absolute Time
    (seconds since January 1, 2001). We convert it to a string format that AppleScript can understand.
    """
    # Convert last_date to a Unix timestamp by adding the offset (978307200 seconds) then to UTC.
    last_date_seconds = last_date / 1e9
    unix_time = last_date_seconds + 978307200
    dt = datetime.utcfromtimestamp(unix_time)
    # Format the date string in a way that AppleScript can parse.
    date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    applescript = f'''
    set thresholdDate to date "{date_str}"
    tell application "Mail"
        set matchingMessages to messages of inbox whose read status is false and date sent > thresholdDate
        set output to ""
        repeat with msg in matchingMessages
            set msgSubject to subject of msg
            set msgSender to sender of msg
            set msgDate to date sent of msg
            set output to output & "Subject: " & msgSubject & ", Sender: " & msgSender & ", Date: " & (msgDate as string) & "\n"
        end repeat
        return output
    end tell
    '''
    process = subprocess.Popen(["osascript", "-e", applescript],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    out, err = process.communicate()
    if err and err.strip():
        return f"Error: {err.decode('utf-8')}"
    unread = out.decode("utf-8").strip()
    print(unread)
    try:
        model_name = "llama3.2"  # Replace with your local model name in Ollama.
        prompt = "Look at these emails. Ignore any marketing emails. Then return a 160 character summary of topics and senders. Return only the summary with no introduction."
        # Create a summarisation prompt.
        try:
            result = subprocess.check_output(["ollama", "run", model_name, prompt + "Emails: " + unread],
                                             stderr=subprocess.STDOUT)
            print(result.decode("utf-8").strip())
            return result.decode("utf-8").strip()
        except Exception as e:
            return f"Error running Ollama model: {e}"
    except Exception as e:
        print("Error using email summary", e)
        return "Error using email summary"

def get_contact_name(phone_number):
    """
    Looks up the contact name for a given phone number using the macOS Contacts app.
    
    Parameters:
        phone_number (str): The phone number to look up.
        
    Returns:
        str: The contact name if found, or 'Unknown' if no match.
    """
    # AppleScript to find the contact by phone number
    applescript = f'''
    tell application "Contacts"
        repeat with person in people
            repeat with phone in phones of person
                if value of phone contains "{phone_number}" then
                    return name of person
                end if
            end repeat
        end repeat
    end tell
    return "Unknown"
    '''
    try:
        # Execute the AppleScript and get the result
        result = subprocess.check_output(["osascript", "-e", applescript], text=True).strip()
        return result if result else "Unknown"
    except subprocess.CalledProcessError as e:
        return f"Error: {e}"

def summarize_unread_messages(last_date):
    """
    Retrieves new inbound (unread) messages from the Apple Messages database with a timestamp greater than last_date.
    This function returns only messages that are still unread (is_read = 0).
    Note: Adjust the query if your Messages database uses a different column name.
    """
    db_path = os.path.expanduser("~/Library/Messages/chat.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # Added "AND is_read = 0" to filter only unread messages.
    cursor.execute("""SELECT handle.id as handle, text, date, is_from_me FROM message 
                JOIN handle ON message.handle_id = handle.ROWID
                   WHERE text != 'None' AND is_from_me = 0 AND is_read = 0 AND date > ? ORDER BY date ASC""", (last_date,))
    results = cursor.fetchall()
    conn.close()
    messages_list = []
    for row in results:
        messages_list.append({
            "text": row["text"],
            "date": row["date"],
            "from": row["handle"],
            #"from": get_contact_name(row["handle"]),
        })
    if messages_list:
        model_name = "llama3.2"  # Replace with your local model name in Ollama.
        # Create a summarisation prompt.
        prompt = f"Summarize these messages, fit within 160 characters. Include the sender name. The messages will all be to the user: {messages_list}"
        print(prompt)
        try:
            result = subprocess.check_output(["ollama", "run", model_name, prompt],
                                             stderr=subprocess.STDOUT)
            return result.decode("utf-8").strip()
        except Exception as e:
            return f"Error running Ollama model: {e}"
    else:
        print("No messages to summarize.")
        return "No new messages"

def process_message(message_text, last_date):
    """
    Classifies the (post-prefix) command text, calls the appropriate helper, and returns the final SMS reply.
    For the two lookup commands (MAIL_SEARCH and MESSAGES_SEARCH), we use the current last_date.
    For these, we then pass the retrieved raw content to the local Ollama model for summarisation.
    """
    command_type = classify_command(message_text)
    print(f"Command classified as: {command_type}")
    
    if command_type == "DIRECTIONS":
        result = get_directions(message_text)
    elif command_type == "OPENINGTIMES":
        result = get_openingtimes(message_text)
    elif command_type == "CHATGPT":
        result = get_chatgpt(message_text)
    elif command_type == "WEB_SEARCH":
        result = perform_web_search(message_text)
    elif command_type == "WEATHER":
        result = get_weather(message_text,GOOGLE_DIRECTIONS_API_KEY)
    elif command_type == "EMAIL_SUMMARY":
        result = summarize_unread_emails(last_date)
    elif command_type == "EMAIL_SEARCH":
        result = search_emails(message_text)
    elif command_type == "MESSAGES_SUMMARY":
        result = summarize_unread_messages(last_date)
    else:
        result = "Sorry, I did not understand your command."
    
    return result

def send_sms_via_bulksms(message):
    """
    Sends an SMS reply using the BulkSMS API.
    """
    payload = {
        "to": MY_NUMBER,
        "body": message,
    }
    try:
        response = requests.post(
            BULKSMS_ENDPOINT,
            json=payload,
            auth=(BULKSMS_USERNAME, BULKSMS_PASSWORD)
        )
        if response.status_code in (200, 201):
            print("SMS sent successfully!")
        else:
            print("Failed to send SMS:", response.status_code, response.text)
    except Exception as e:
        print("Error sending SMS via BulkSMS:", e)

# -------------------------------
# Polling for Inbound Commands
# -------------------------------

def get_new_commands(last_date):
    """
    Queries the Apple Messages database for new inbound command messages that:
      - Are not sent by you (is_from_me = 0)
      - Begin with the overall prefix (e.g. "gpt:")
      - Are from your number (matched via the handle table)
      - Have a timestamp greater than last_date
    """
    db_path = os.path.expanduser("~/Library/Messages/chat.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    query = """
    SELECT message.ROWID as id, message.text as text, message.date as date, handle.id as handle
    FROM message
    JOIN handle ON message.handle_id = handle.ROWID
    WHERE message.is_from_me = 0
      AND message.date > ?
      AND handle.id = ?
    ORDER BY message.date ASC
    """

    cur.execute(query, (last_date, MY_NUMBER))
    rows = cur.fetchall()
    conn.close()

    return rows

# -------------------------------
# Main Loop
# -------------------------------

def main():
    print("Starting inbound command polling...")
    last_date = load_last_date()
    print("Starting from last_date =", last_date)
    
    try:
        check_lock()  # Ensure only one instance runs
        commands = get_new_commands(last_date)
        for cmd in commands:
            # Update last_date to avoid reprocessing the same message
            last_date = max(last_date, cmd["date"])
            save_last_date(last_date)
            
            text = cmd["text"]
            if text:
                print("Processing message ID", cmd["id"])
                command_text = text
                # Process the command (pass along last_date for lookup helpers)
                reply = process_message(command_text, last_date)
                print("Reply generated:", reply)
                # Send the SMS reply via BulkSMS
                send_sms_via_bulksms(reply)
    except Exception as e:
        print("Error in polling loop:", e)

    finally:
        remove_lock()  # Ensure lock is removed on exit
    

if __name__ == '__main__':
    main()

