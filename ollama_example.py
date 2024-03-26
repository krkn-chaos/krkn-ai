from langchain_community.llms import Ollama
import json
import os
import tempfile
import shutil
from langchain_community.document_loaders import JSONLoader
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import OllamaEmbeddings

from langchain.schema.output_parser import StrOutputParser
from langchain.schema.runnable import RunnablePassthrough
from langchain.prompts import ChatPromptTemplate
from elasticsearch import Elasticsearch
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


ollama_endpoint="http://192.168.0.107:11434"
ollama_model = "llama2-uncensored"

os.environ["HUGGINGFACEHUB_API_TOKEN"] = "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"
os.environ["CURL_CA_BUNDLE"] = ""

data = []
elastic = Elasticsearch("https://search-perfscale-dev-chmf5l4sh66lvxbnadi4bznl3a.us-west-2.es.amazonaws.com")
print("> Querying elastic search https://search-perfscale-dev-chmf5l4sh66lvxbnadi4bznl3a.us-west-2.es.amazonaws.com")
resp = elastic.search(index="ripsaw-kube-burner", body={
    "query": {
        "query_string": {
            "query": "metricName.keyword: podLatencyQuantilesMeasurement AND quantileName.keyword: Ready AND metadata.ocpMajorVersion.keyword: *"}
    },
    "size": 1000,
    #"sort": [{ "timestamp": "desc" }],
    "fields":["uuid", "metadata.ocpMajorVersion.keyword","P99"]
})
print(f'> {len(resp["hits"]["hits"])} documents retrieved')




elems = []
ocp_version = ""
for document in resp["hits"]["hits"]:
    elems.append({
        "uuid": document["fields"]["uuid"][0],
        "metric_name": "podLatencyQuantilesMeasurement",
        "latency": document["fields"]["P99"][0],
        "ocp_version": document["fields"]["metadata.ocpMajorVersion.keyword"][0]
    })

json_data = json.dumps(elems, indent=2)

with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
    f.write(json_data)
    f.flush()
    filename = f.name

try:
    shutil.rmtree("chroma_db")
except Exception as e:
    print(f"chroma_db folder not yet created! {e}")

# Embeddings
embeddings = OllamaEmbeddings(base_url=ollama_endpoint, model=ollama_model)
loader = JSONLoader(
    file_path=filename,
    jq_schema='.',
    text_content=False
)

data = loader.load()
print ("> loading the data on Chroma DB vector database")
vectorstore = Chroma.from_documents(data, embeddings, persist_directory="./chroma_db")
retriever = vectorstore.as_retriever()

llm = Ollama(base_url=ollama_endpoint, model=ollama_model)

# Prompt
print ("> connecting to the LLM model")

template = """Answer like a human, each of the items in the following JSON documents represents a latency test result,
where each sample is surrounded by brackets. The lower average latency in the JSON represents the better result.
context: {context}

Question: {question}
"""

prompt = ChatPromptTemplate.from_template(template)
chain = (
    {"context": retriever,  "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)

while True:
    query = input("Ask me anything about the metrics collected: ")
    output = chain.invoke(query)
    print(output)
