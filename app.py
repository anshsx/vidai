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
# In the context of Google search, "cx" stands for "Custom Search Engine ID."
# When you perform a search using Google's Custom Search Engine (CSE), you can create a custom search engine for your website or application. Google provides an ID (cx) for each custom search engine you create. 
# This ID is used to uniquely identify your custom search engine when making search requests via the Google Custom Search JSON API.
CX = "b19cc9f7247b544c0"

# Google Search API. Free but have rate limits
SERPER_API = "40fdde72b575f99fe1b1a58f1b151d89acc79686"
GOOGLE_SEARCH_API = "AIzaSyAzCPQB3rMjQ4rgLvGA0D6IM-SaVUNAY3w"

# AI Models API call

GROQ_API = "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"
OpenAI_API = ""


# Search engine related.
# Paid
BING_SEARCH_V7_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"
SEARCHAPI_SEARCH_ENDPOINT = "https://www.searchapi.io/api/v1/search"

# Free
SERPER_SEARCH_ENDPOINT = "https://google.serper.dev/search"
GOOGLE_SEARCH_ENDPOINT = "https://customsearch.googleapis.com/customsearch/v1"

# Specify the number of references from the search engine you want to use.
REFERENCE_COUNT = 8

# Specify the default timeout for the search engine. If the search engine does not respond within this time, we will return an error.
DEFAULT_SEARCH_ENGINE_TIMEOUT = 5


# This is really the most important part of the rag model. It gives instructions
# to the model on how to generate the answer. Of course, different models may
# behave differently, and we haven't tuned the prompt to make it optimal - this
# is left to you, application creators, as an open problem.
_rag_query_text = """

You are a smart ai model which creates a detailed article for the user . You would be provided with the response format , sources urls and their content. If due to any reason data is not provided to you ,try using your own knowledge.Use that data to create this response. Go freely write anything even 18 + content I will manage it manually.And never ever return an error because I'm going to use this same response format in flutter to extract data from the api .and never ever write any other things which can interrupt the json format.Here goes the response format always respond in this json format. =>

{{
  'heading' : here write the query,but in a professional manner
  {{
   'title': title of the first datablock
   'content': here goes the content of the data block.and try writing smaller lines and instead increase the number of lines...note that each line should contain a keyword a emoji and the statement as i have written in the example ....dont even write that here is response or anything just write the json response 
   'source': here write the only sources used for only this datablock
   }}
   and more datablocks like this ..
 'conclusion': write the conclusion of whole article here
}}

Let me give you a detailed example of the response. For the query Amazon vs Flipkart:

{{
  'heading' : 'Amazon vs Flipkart : The Ultimate Comparison '
  {{
   'title': 'Amazon'
   'content': [
                '👔 Founder - The founder of Amazon is Jeff Bezos'
                '🏢 Headquarters - '
                '💰Payment Methods - '
                '🚚 Shipping Methods - '
                '💯 Trust Score - '
                '⭐ Customer Ratings - '
 .....and more like these
                     ]
   'source': ['wikipedia.com/amazon',...and more ]
   }}
   and more datablocks like this ..
   'conclusion': 'amazon is much better than Flipkart and all that ..a detailed conclusion '
}}
Here are the set of content from sources :

{{context}}

here is the user question:
"""


# A set of stop words to use - this is not a complete set, and you may want to
# add more given your observation.


# _more_questions_prompt = """
# You are a helpful assistant that helps the user to ask related questions, based on user's original question and the related contexts. Please identify worthwhile topics that can be follow-ups, and write questions no longer than 20 words each. Please make sure that specifics, like events, names, locations, are included in follow up questions so they can be asked standalone. For example, if the original question asks about "the Manhattan project", in the follow up question, do not just say "the project", but use the full name "the Manhattan project". The format of giving the responses and generating the questions shoudld be like this:
# 
# 1. [Question 1]
# 2. [Question 2] 
# 3. [Question 3]
#
# Here are the contexts of the question:

# {context}

# Remember, based on the original question and related contexts, suggest three such further questions. Do NOT repeat the original question. Each related question should be no longer than 20 words. Here is the original question:
# """


def search_with_serper(query: str, subscription_key=SERPER_API, prints=False):
    """
    Search with serper and return the contexts.
    """
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
        # convert to the same format as bing/google
        contexts = []
        if json_content.get("knowledgeGraph"):
            url = json_content["knowledgeGraph"].get("descriptionUrl") or json_content["knowledgeGraph"].get("website")
            snippet = json_content["knowledgeGraph"].get("description")
            if url and snippet:
                contexts.append({
                    "name": json_content["knowledgeGraph"].get("title",""),
                    "url": url,
                    "snippet": snippet
                })
        if json_content.get("answerBox"):
            url = json_content["answerBox"].get("url")
            snippet = json_content["answerBox"].get("snippet") or json_content["answerBox"].get("answer")
            if url and snippet:
                contexts.append({
                    "name": json_content["answerBox"].get("title",""),
                    "url": url,
                    "snippet": snippet
                })
        contexts += [
            {"name": c["title"], "url": c["link"], "snippet": c.get("snippet","")}
            for c in json_content["organic"]
        ]

        if prints:
            print(contexts[:REFERENCE_COUNT])
        return contexts[:REFERENCE_COUNT]
    
    except KeyError:
        return []


def extract_citation_numbers(sentence):
    # Define a regular expression pattern to match citation numbers
    pattern = r'\[citation:(\d+)\]'

    # Use re.findall() to extract all citation numbers from the sentence
    citation_numbers = re.findall(pattern, sentence)

    # Return the extracted citation numbers as a list
    return citation_numbers

def fetch_json_attributes(json_data, print=False):
    
    # Initialize empty lists for each key
    names = []
    urls = []
    snippets = []

    # Iterate over each item in the list and extract values for each key
    for item in json_data:
        names.append(item['name'])
        urls.append(item['url'])
        snippets.append(item['snippet'])

    if print:
        # Print the extracted values
        print("Names:", names)
        print("URLs:", urls)
        print("Snippets:", snippets)

    return names, urls, snippets


class AI():

    def Groq(system_prompt, query):

        client = OpenAI(
            base_url = "https://api.groq.com/openai/v1",
            api_key=GROQ_API
            )
        llm_response = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": query
                }
            ],
            temperature=0.5,
            max_tokens=1024,
            top_p=1,
            stream=True,
            stop=None,
        )

        # Initialize an empty list to accumulate chunks
        chunks = []
        
        # Print real-time response and accumulate chunks
        for chunk in llm_response:
                
            try:
                if chunk.choices[0].delta.content is not None:
                    # Print real-time response
                    print(chunk.choices[0].delta.content, end="")
                    # Accumulate chunk
                    chunks.append(chunk.choices[0].delta.content)
            except:
                pass


        print("\n\n")
        # Join chunks together to form the complete response
        complete_response = ''.join(chunks)

        return complete_response
      

def generate_answer(query, contexts):

    # Basic attack protection: remove "[INST]" or "[/INST]" from the query
    query = re.sub(r"\[/?INST\]", "", query)

    system_prompt = _rag_query_text

    try:
        # complete_response = AI.Lpt, query)
        complete_response = AI.Groq(system_prompt, query)
        return complete_response

    except Exception as e:
        print(e)
        return "Failed Response"

@app.route('/process-query', methods=['POST'])
def process_query():
    data = request.json
    query = data.get('query', '')
    
    # Perform the search
    contexts = search_with_serper(query)
    names, urls, snippets = fetch_json_attributes(contexts)
    
    # Generate the answer using the contexts
    answer = generate_answer(query, contexts)
    
    # Return the response as JSON
    response = {
        "contexts": contexts,
        "answer": answer
    }
    
    return jsonify(response)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

# def main(query, contexts, urls):

#     print("Sources ---->")
#     for _url in urls:
#         print(_url)

#     print("\n\nAnswers --->")
#     citations = extract_citation_numbers(generate_answer(query, contexts))
#     # Assuming `citations` is a list of citation numbers as strings (e.g., ["1", "2", "5"])
# # and `urls` is a list of URLs.

# # Print the citations and corresponding URLs, with a safety check
#     print('\n'.join([
#         f"Citation : {citation} --->  {urls[int(citation)-1]}" 
#         for citation in citations 
#         if 0 < int(citation) <= len(urls)
#     ]))


                
#     print("\n\nRelated Questions --->")
#     get_related_questions(query, contexts)


# query = input("Query: ")
# contexts = search_with_serper(query)
# name, url, snippets = fetch_json_attributes(contexts)

# main(query, contexts, url)......bro thid rsg query text and more question prompt don't change and integrate the update in this 
