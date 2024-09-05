# Groq Llama 2 Model API integrated for generating answers based on contexts
# Search, fetch related contexts and generate related questions and answers using the Llama model API.

import json
import re
import threading
import requests
import traceback
from fastapi import HTTPException
from openai import OpenAI
from fastapi import FastAPI, HTTPException
from flask import Flask, request, jsonify
import json

app = Flask(__name__)

# Constants for Google Search APIs
CX = "b19cc9f7247b544c0"
SERPER_API = "40fdde72b575f99fe1b1a58f1b151d89acc79686"
GOOGLE_SEARCH_API = "AIzaSyAzCPQB3rMjQ4rgLvGA0D6IM-SaVUNAY3w"

# AI Model API key
GROQ_API = "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"

# Search API Endpoints
BING_SEARCH_V7_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"
SEARCHAPI_SEARCH_ENDPOINT = "https://www.searchapi.io/api/v1/search"
SERPER_SEARCH_ENDPOINT = "https://google.serper.dev/search"
GOOGLE_SEARCH_ENDPOINT = "https://customsearch.googleapis.com/customsearch/v1"

# Settings
REFERENCE_COUNT = 8
DEFAULT_SEARCH_ENGINE_TIMEOUT = 5

# Template for generating answers using contexts
_rag_query_text = """
{{You are a large language AI assistant built by Ansh Sharma. You are given a user question, and please write a clean, concise and accurate answer to the question. You will be given a set of related contexts to the question, each starting with a reference number like [[citation:x]], where x is a number. Please use the context and cite the context at the end of each sentence if applicable.

 Your answer must be correct, accurate, and written by an expert using an unbiased and professional tone. Please limit to 1024 tokens. Do not give any information that is not related to the question, and do not repeat. Say "information is missing on" followed by the related topic, if the given context does not provide sufficient information.

 You are an AI search engine and a helpful AI agent. You have to create a researched professional answer like this I'm creating. Here are the examples:

 The response format: 

 {{
   {{
     "main": "Main Heading of the query.. create it in a professional way"
   }},
   {{
     "title": "title ..create it by your own",
     "keywords": ["1-3 word title for each content"],
     "Content": ["content and the number of these lines should be equal to keywords count that is each keyword contains a para or a line for say"],
     "Emojis": ["emojis different ones for each keyword"],
     "Conclusion": "conclusion of the whole thing.."
   }},
   {{
     "title": "title ..create it by your own",
     "keywords": ["1-3 word title for each content"],
     "Content": ["content and the number of these lines should be equal to keywords count that is each keyword contains a para or a line for say"],
     "Emojis": ["emojis different ones for each keyword"],
     "Conclusion": "conclusion of the whole thing.."
   }},
   ...and goes on.. create a minimum of 6 like these.. can be more but never be less
   {{
     "rltdq": ["related questions list that can strike user mind"] 
   }}
 }}

 OK, so this was the format. Now a sample example for the query "Amazon vs Flipkart":

 {{
   {{
     "main": "Amazon Vs Flipkart: \n The Ultimate Comparison"
   }},
   {{
     "title": "Amazon",
     "keywords": ["Founder", "Headquarters", "Shipping", "Payment Methods", "Customer ratings", "Trust Score"],
     "Content": [
       "Founder of Amazon is Jeff Bezos, born and other etc details...",
       "Headquarters of Amazon are located here... and more things about it",
       ...all others like this
     ],
     "Emojis": ["different emoji for each keyword"],
     "Conclusion": "conclusion for all that"
    }},
   same for Flipkart now... then other things like which is better in which category... in short, write everything about the query so the user doesn't need to go to some other place to search for that query.
 }}

 Remember that I'm using it as an API in my Flask app, so always give a response in JSON format, and the keyword count should be equal to content lines should be equal to the number of emojis... so that each keyword gets a content line and an emoji... OK?
 These titles should be a minimum of 4 and can be more but not try exceeding 4. Create more if needed... use your knowledge also to create the best response and don't write anything except the JSON response...
 This is an important note remember each keyword should have 1 content line and a emoji...keyword count == content lines == emoji count..and remeber 1 content line means a line written in double quotes ...
}}

This is an important note remember each keyword should have 1 content line and a emoji...keyword count == content lines == emoji count..and return all data in json format ..dont write anything else 
Please cite the contexts with the reference numbers, in the format [citation:x]. If a sentence comes from multiple contexts, please list all applicable citations, like [citation:3][citation:5]. Other than code and specific names and citations, your answer must be written in the same language as the question. If there are too many citations, choose the best of them.
Dont write anything except this json form, it should not seem to user that this is an ai generated response ...
Here are the set of contexts:

{{context}}

Remember, don't blindly repeat the contexts. And here is the user question:
"""


# Stop words list
stop_words = [
    "<|im_end|>",
    "[End]",
    "[end]",
    "\nReferences:\n",
    "\nSources:\n",
    "End.",
]

# Follow-up questions prompt
_more_questions_prompt = """
You are a helpful assistant that helps the user to ask related questions, based on user's original question and the related contexts. Please identify worthwhile topics that can be follow-ups, and write questions no longer than 20 words each. Please make sure that specifics, like events, names, locations, are included in follow-up questions so they can be asked standalone. For example, if the original question asks about "the Manhattan project", in the follow-up question, do not just say "the project", but use the full name "the Manhattan project". The format of giving the responses and generating the questions should be like this:

1. [Question 1]
2. [Question 2] 
3. [Question 3]

Here are the contexts of the question:

{context}

Remember, based on the original question and related contexts, suggest three such further questions. Do NOT repeat the original question. Each related question should be no longer than 20 words. Here is the original question:
"""

# Function to perform search using Serper API
def search_with_serper(query: str, subscription_key=SERPER_API, prints=False):
    payload = json.dumps({
        "q": query,
        "num": (
            REFERENCE_COUNT
            if REFERENCE_COUNT % 10 == 0
            else (REFERENCE_COUNT // 10 + 1) * 10
        ),
    })
    headers = {"X-API-KEY": subscription_key, "Content-Type": "application/json"}
    response = requests.post(
        SERPER_SEARCH_ENDPOINT,
        headers=headers,
        data=payload,
        timeout=DEFAULT_SEARCH_ENGINE_TIMEOUT,
    )
    if not response.ok:
        raise HTTPException(response.status_code, "Search engine error.")
    json_content = response.json()

    if prints:
        print(json_content)
        print("\n\n\n-------------------------------------------------------------------------------\n\n\n")

    try:
        contexts = []
        if json_content.get("knowledgeGraph"):
            url = json_content["knowledgeGraph"].get("descriptionUrl") or json_content["knowledgeGraph"].get("website")
            snippet = json_content["knowledgeGraph"].get("description")
            if url and snippet:
                contexts.append({
                    "name": json_content["knowledgeGraph"].get("title", ""),
                    "url": url,
                    "snippet": snippet
                })
        if json_content.get("answerBox"):
            url = json_content["answerBox"].get("url")
            snippet = json_content["answerBox"].get("snippet") or json_content["answerBox"].get("answer")
            if url and snippet:
                contexts.append({
                    "name": json_content["answerBox"].get("title", ""),
                    "url": url,
                    "snippet": snippet
                })
        contexts += [
            {"name": c["title"], "url": c["link"], "snippet": c.get("snippet", "")}
            for c in json_content["organic"]
        ]

        if prints:
            print(contexts[:REFERENCE_COUNT])
        return contexts[:REFERENCE_COUNT]
    
    except KeyError:
        return []

# Function to extract citation numbers
def extract_citation_numbers(sentence):
    pattern = r'citation:(\d+)'
    citation_numbers = re.findall(pattern, sentence)
    return citation_numbers

# Function to fetch attributes from JSON data
def fetch_json_attributes(json_data, print=False):
    names = []
    urls = []
    snippets = []
    for item in json_data:
        names.append(item['name'])
        urls.append(item['url'])
        snippets.append(item['snippet'])
        if print:
            print(f"Name: {item['name']}")
            print(f"URL: {item['url']}")
            print(f"Snippet: {item['snippet']}")
            print("\n-------------------------------\n")
    return names, urls, snippets

# Function to clean text by removing stop words
def clean_text(text, stop_words_list=stop_words):
    for stop_word in stop_words_list:
        text = text.replace(stop_word, "")
    return text.strip()

# Function to call the Llama 2 model for generating answers based on contexts
def query_llama_2_with_contexts(query, contexts, model_api_key=GROQ_API):
    headers = {
        "Authorization": f"Bearer {model_api_key}",
        "Content-Type": "application/json"
    }
    payload = json.dumps({
        "query": query,
        "contexts": contexts
    })
    try:
        response = requests.post("https://llama2.model.api/ask", headers=headers, data=payload, timeout=30)
        if response.status_code == 200:
            result = response.json()
            return result['answer']  # Return the AI-generated answer
        else:
            raise HTTPException(status_code=response.status_code, detail="Llama 2 API error.")
    except requests.exceptions.RequestException as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Request to Llama 2 API failed.")

# Function to generate follow-up questions based on contexts
def generate_followup_questions(original_question, contexts, model_api_key=GROQ_API):
    headers = {
        "Authorization": f"Bearer {model_api_key}",
        "Content-Type": "application/json"
    }
    followup_prompt = _more_questions_prompt.format(context=contexts)
    payload = json.dumps({
        "prompt": followup_prompt,
        "max_tokens": 100
    })
    try:
        response = requests.post("https://llama2.model.api/generate", headers=headers, data=payload, timeout=30)
        if response.status_code == 200:
            result = response.json()
            return result['questions']  # Return the list of follow-up questions
        else:
            raise HTTPException(status_code=response.status_code, detail="Llama 2 API error during follow-up generation.")
    except requests.exceptions.RequestException as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Request to Llama 2 API failed.")

# Flask route to handle search and answer generation
@app.route('/search-and-answer', methods=['POST'])
def search_and_answer():
    try:
        data = request.json
        user_query = data.get('query')
        if not user_query:
            raise HTTPException(status_code=400, detail="Query is required.")
        
        # Perform search using Serper API
        search_results = search_with_serper(user_query)
        if not search_results:
            raise HTTPException(status_code=404, detail="No search results found.")

        # Extract names, urls, and snippets from search results
        names, urls, snippets = fetch_json_attributes(search_results)
        
        # Clean up and compile the snippets for context generation
        contexts = "\n".join([clean_text(snippet) for snippet in snippets])

        # Generate an answer using Llama 2 based on the search contexts
        answer = query_llama_2_with_contexts(user_query, contexts)

        # Generate follow-up questions based on the context
        followup_questions = generate_followup_questions(user_query, contexts)

        # Return a response with the answer and follow-up questions
        response = {
            "answer": answer,
            "follow_up_questions": followup_questions,
            "sources": [{"name": name, "url": url} for name, url in zip(names, urls)]
        }
        return jsonify(response)

    except HTTPException as e:
        return jsonify({"error": str(e.detail)}), e.status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "An unexpected error occurred."}), 500

# Running the Flask app
if __name__ == '__main__':
    app.run(debug=True)
