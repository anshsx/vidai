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
 This is a important note remember each keyword should have 1 content line and a emoji...keyword count == content lines == emoji count..and remeber 1 content line means a line written in double quotes ...
}}

This is a important note remember each keyword should have 1 content line and a emoji...keyword count == content lines == emoji count..and remeber 1 content line means a line written in double quotes ...and return all data in json format ..dont write anything else 
Dont write anything except this json form, it should not seem to user that this is a ai generated response ...
Here are the set of contexts:

{{context}}

here is the user question:
"""


# A set of stop words to use - this is not a complete set, and you may want to
# add more given your observation.
stop_words = [
    "<|im_end|>",
    "[End]",
    "[end]",
    "\nReferences:\n",
    "\nSources:\n",
    "End.",
]

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
    

def get_related_questions(query, contexts):
        
        system_prompt = _more_questions_prompt.format(
                            context="\n\n".join([c["snippet"] for c in contexts])
                        )

        try:
            # complete_response = AI.Lepton(system_prompt, query.)
            # complete_response = AI.DeepSeek(system_prompt, query)
            complete_response = AI.Groq(system_prompt, query)
            return complete_response
        
        except Exception as e:
            print(e)
            # For any exceptions, we will just return an empty list.
            return []
        

def generate_answer(query, contexts):

    # Basic attack protection: remove "[INST]" or "[/INST]" from the query
    query = re.sub(r"\[/?INST\]", "", query)

    system_prompt = _rag_query_text.format(
                context="\n\n".join(
                    [f"[[citation:{i+1}]] {c['snippet']}" for i, c in enumerate(contexts)]
                )
            )

    try:
        # complete_response = AI.Lepton(system_prompt, query)
        # complete_response = AI.DeepSeek(system_prompt, query)
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
