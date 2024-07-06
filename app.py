import json
import re
import threading
import requests
import traceback
from fastapi import HTTPException
from openai import OpenAI
from flask import Flask,request,jsonify

app = Flask(__name__)

# In the context of Google search, "cx" stands for "Custom Search Engine ID."
# When you perform a search using Google's Custom Search Engine (CSE), you can create a custom search engine for your website or application. Google provides an ID (cx) for each custom search engine you create. 
# This ID is used to uniquely identify your custom search engine when making search requests via the Google Custom Search JSON API.
CX = "b19cc9f7247b544c0"
CX_KEY = "AIzaSyB5o1o4jH8-i1XMQJzASfJenBJ7kC3XEPk"

# Google Search API. Free but have rate limits
SERPER_API = "878b5d783683d5bf2dee3900fec43b3fbbe3bebe"
GOOGLE_SEARCH_API = "d12402bb42msh61b181a69650f53p1d14e6jsn33dd98c6f779"

# AI Models API call
DEEPSEEK_API = ""
Lepton = "nqvhgp7a6s3uiwgn7nfxwjkz5zg44iin"
LEPTON_API = ""
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
DEFAULT_SEARCH_ENGINE_TIMEOUT = 10

# This is really the most important part of the rag model. It gives instructions
# to the model on how to generate the answer. Of course, different models may
# behave differently, and we haven't tuned the prompt to make it optimal - this
# is left to you, application creators, as an open problem.
_rag_query_text = """
You are a large language AI assistant built by Ansh Sharma. You are given a user question, and please write clean, concise and accurate answer to the question. You will be given a set of related contexts to the question, each starting with a reference number like [[citation:x]], where x is a number. Please use the context and cite the context at the end of each sentence if applicable.
Also don't say these type of contexts like I'm happy to help you with your question!,If you meant to ask a different question, please feel free to rephrase it. If you meant to ask about the arithmetic operation..because i am going to use your answer in a articlemaking app....andit should not be recognised that answer is from an AI Model.
Your answer must be correct, accurate and written by an expert using an unbiased and professional tone. Please limit to 1024 tokens. Do not give any information that is not related to the question, and do not repeat. Say "information is missing on" followed by the related topic, if the given context do not provide sufficient information.

Please cite the contexts with the reference numbers, in the format [citation:x]. If a sentence comes from multiple contexts, please list all applicable citations, like [citation:3][citation:5]. Other than code and specific names and citations, your answer must be written in the same language as the question. If there are too many citations, choose the best of them
Here are the set of contexts:

{context}

Remember, don't blindly repeat the contexts. And here is the user question:
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

# This is the prompt that asks the model to generate related questions to the
# original question and the contexts.
# Ideally, one want to include both the original question and the answer from the
# model, but we are not doing that here: if we need to wait for the answer, then
# the generation of the related questions will usually have to start only after
# the whole answer is generated. This creates a noticeable delay in the response
# time. As a result, and as you will see in the code, we will be sending out two
# consecutive requests to the model: one for the answer, and one for the related
# questions. This is not ideal, but it is a good tradeoff between response time
# and quality.
_more_questions_prompt = """
You are a helpful assistant that helps the user to ask related questions, based on user's original question and the related contexts. Please identify worthwhile topics that can be follow-ups, and write questions no longer than 20 words each. Please make sure that specifics, like events, names, locations, are included in follow up questions so they can be asked standalone. For example, if the original question asks about "the Manhattan project", in the follow up question, do not just say "the project", but use the full name "the Manhattan project". The format of giving the responses and generating the questions shoudld be like this:

1. [Question 1]
2. [Question 2] 
3. [Question 3]

Here are the contexts of the question:

{context}

Remember, based on the original question and related contexts, suggest three such further questions. Do NOT repeat the original question. Each related question should be no longer than 20 words. Here is the original question:
"""

# CODE
#### WEB SEARCH FUNCTIONS
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

def search_with_google(query: str, subscription_key= GOOGLE_SEARCH_API, cx=CX ):
    """
    Search with google and return the contexts.
    """
    params = {
        "key": subscription_key,
        "cx": cx,
        "q": query,
        "num": REFERENCE_COUNT,
    }
    response = requests.get(
        GOOGLE_SEARCH_ENDPOINT, params=params, timeout=DEFAULT_SEARCH_ENGINE_TIMEOUT
    )
    if not response.ok:
        raise HTTPException(response.status_code, "Search engine error.")
    json_content = response.json()
    try:
        contexts = json_content["items"][:REFERENCE_COUNT]
    except KeyError:
        return []
    print(contexts)
    # return contexts
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
#### AI MODELS API INTEGRATION
class AI():

    def DeepSeek(system_prompt, query):
        client = OpenAI(
            api_key=DEEPSEEK_API, 
            base_url="https://api.deepseek.com/v1")
        
        llm_response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": query},
                    ],
                    max_tokens=1024,
                    stop=stop_words,
                    stream=True,
                    temperature=0.9,
                ) 
        
        # Initialize an empty list to accumulate chunks
        chunks = []
        
        # Print real-time response and accumulate chunks
        for chunk in llm_response:
            if chunk.choices[0].delta.content is not None:
                # Print real-time response
                print(chunk.choices[0].delta.content, end="")
                
                # Accumulate chunk
                chunks.append(chunk.choices[0].delta.content)


        print("\n\n")
        # Join chunks together to form the complete response
        complete_response = ''.join(chunks)

        return complete_response
    

    def Lepton(system_prompt, query):
        client = OpenAI(
        base_url="https://mixtral-8x7b.lepton.run/api/v1/",
        api_key=LEPTON_API
        )

        llm_response = client.chat.completions.create(
            model="mixtral-8x7b",
            messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": query},
                    ],
                    max_tokens=1024,
                    stop=stop_words,
                    stream=True,
                    temperature=0.9,
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


    def Openai(system_prompt, query):

        client = OpenAI(
            base_url = "https://api.openai.com/v1",
            api_key=OpenAI_API
            )
        llm_response = client.chat.completions.create(
            model="llama2-70b-4096",
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
#### FUNCTION CALLS
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
    
def image_urls(query,num=5):
    search_url = "https://www.googleapis.com/customsearch/v1"
    params = { 
              "q": query,
              "cx": CX,
              "key": CX_KEY,
              "search_type": "image",
              "num": num
              }
    
    response = requests.get(search_url,params=params)
    response.raise_for_status()
    search_results = response.json()

    image_links = [item["link"] for item in search_results.get("items",[])]
    return image_links



# def main(query, contexts, urls):

#     print("Sources ---->")
#     for _url in urls:
#         print(_url)

#     print("\n\nAnswers --->")
#     citations = extract_citation_numbers(generate_answer(query, contexts))
#     print('\n'.join([f"Citation : {citation} --->  {urls[int(citation)-1]}" for citation in citations]))

                
#     print("\n\nRelated Questions --->")
#     get_related_questions(query, contexts)

#     print("\n\nImages Links --->")
#     image_links = image_urls(query)
#     for link in image_links:
#         print(link)
    
# #### RESULTS
# query = input("Enter your query : ")
# contexts = search_with_serper(query)
# name, url, snippets = fetch_json_attributes(contexts)
# main(query, contexts, url)

def main(query, contexts, urls):
    # Generate the answer
    answer = generate_answer(query, contexts)
    
    # Extract citation numbers from the answer
    citations = extract_citation_numbers(answer)
    
    # Map citation numbers to URLs
    citation_links = [urls[int(citation) - 1] for citation in citations]
    
    # Get related questions
    related_questions = get_related_questions(query, contexts)
    
    # Get image URLs
    image_links = image_urls(query)
    
    # Construct the API response
    response = {
        "Answers": generate_answer(query, contexts),
        "Citations": [f"Citation : {citation} --->  {urls[int(citation)-1]}" for citation in citations],
        "Related Questions": get_related_questions(query, contexts),
        "Image Links": image_links,
        "Sources": urls
    }
    
    return response

@app.route('/query', methods=['GET'])
def query():
    query_param = request.args.get('search')
    if not query_param:
        return jsonify({"error": "No search parameter provided"}), 400
    
    contexts = search_with_serper(query_param)
    names, urls, snippets = fetch_json_attributes(contexts)
    response = main(query_param, contexts, urls)
    
    return jsonify(response)


