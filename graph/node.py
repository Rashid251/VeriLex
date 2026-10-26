# node.py
# The actual work done at each step of the graph.
# Each function takes the current state, does one job, and returns the updated state.
# LangGraph calls these in order, following the edge defined in graph.py

from rag.embedding import EuriEmbedder   # turns the question text into a vector, so can search qdrant with it.
from rag.vector_store import VectorStore  # runs the similarity search against the stored chunks
from graph.state import GraphState       # the shared state shape every node reads from and writes back to it.
from rag.chat_model import EuriChatModel
import json
import ast

TOP_K = 5              # how many chunks to pull back per retrieval

def retrieve(state: GraphState) -> GraphState:
    # first node in the flow: turns the current question into chunks from Qdrant.
    embedder = EuriEmbedder()
    vector = embedder([state["question"]])[0]
    # embeddes takes the list and returns the list, so we grab the single result with [0]

    store = VectorStore()
    documents = store.query(vector=vector, top_k=TOP_K)
    # documents is a list of payloads: [{"text": ..., "source": ..., "page": ...}, ...]

    state["documents"] = documents   # save the retrieved chunks into state so the next node (grade_documents) can use them

    return state


# 2. grade_documents node:
# This node is the heart of the CRAG's "corrective" part
# For every chunk retrieve just pulled back, it asks the chat model a simple yes/no-style question
# the model is instructed to reply with just one word so parsing stays simple.

GRADE_SYSTEM_PROMPT = (
    "You grade whether a document is relevant to a question. "
    "Reply with ONLY a JSON array of the words relevant or irrelevant, "
    "one per document, in the same order as the documents given. "
    'Example reply: ["relevant", "irrelevant", "relevant"]'
)
# one call grades every document at once; reply must be a JSON array, same length and order as the docs

def grade_documents(state: GraphState) -> GraphState:
    # second node: one chat model call grades every retrieved chunk at once
    documents = state["documents"]

    numbered_docs = "\n".join(f"Doc {i + 1}: {doc['text']}" for i, doc in enumerate(documents))

    user_prompt = f"Question: {state['question']}\n{numbered_docs}"

    chat_model = EuriChatModel()
    raw_reply = chat_model(GRADE_SYSTEM_PROMPT, user_prompt)

    # Gemini may return strict JSON, fenced JSON, or a Python-style list with
    # single quotes. Normalize all three forms into a Python list.
    cleaned_reply = raw_reply.strip()
    if cleaned_reply.startswith("```"):
        cleaned_reply = cleaned_reply.split("\n", 1)[-1]
        if cleaned_reply.endswith("```"):
            cleaned_reply = cleaned_reply[:-3].strip()

    start = cleaned_reply.find("[")
    end = cleaned_reply.rfind("]")
    candidate = cleaned_reply[start:end + 1] if start >= 0 and end > start else cleaned_reply

    try:
        grades = json.loads(candidate)
    except json.JSONDecodeError:
        try:
            grades = ast.literal_eval(candidate)
        except (ValueError, SyntaxError) as exc:
            raise ValueError(f"Could not parse document grades: {raw_reply}") from exc

    # Some Gemini responses wrap the expected array in one extra array.
    # Normalize that harmless variation before validating the grade count.
    if (
        isinstance(grades, list)
        and len(grades) == 1
        and isinstance(grades[0], list)
    ):
        grades = grades[0]

    if len(grades) != len(documents):
        raise ValueError(f"expected {len(documents)} grades, got {len(grades)}: {raw_reply}")
        # fail loudly instead of silently letting documents and grades fall out of sync
    
    state["document_grades"] = [g.strip().lower() for g in grades]
    # one grade per document, same order as state["documents"]

    return state

# 3. rewrite_query: 
# This third node in CRAG flow runs only when grade_documents decided retrieval is too weak.
# It asks the chat model to reword the question - using both the original question and
# and the query that just failed - then hands the new wording back to retrieve, which
# loops through the qdrant again with better phrasing.

REWRITE_SYSTEM_PROMPT = (
    "You rewrite a search query so it retrieves better results from a document database. "
    "The previous query mostly returned irrelevant documents. "
    "Reply with only the rewritten query text, nothing else."
)
# used when retrieval was weak, to try a differently-worded question before retrieving again

def rewrite_query(state: GraphState) -> GraphState:
    user_prompt = f"Original question: {state['original_question']}\nPrevious query: {state['question']}"
    # gives the model both the true intent and the query that didn't work well.

    chat_model = EuriChatModel()
    new_question = chat_model(REWRITE_SYSTEM_PROMPT, user_prompt).strip()
    # strip removes stray whitespace/newlines around the rewritten query

    state["question"] = new_question
    # overwrites question, so the next retrieve() call searches with the improved wording

    state["retrieval_retries"] += 1
    # counts this attempt, so the conditional edge in graph.py can enforce the max retry limit

    return state


def _relevant_context(state: GraphState) -> str:
    # shared by generate and validate_answer, so both build the exact same context block
    relevant_docs = [
        doc for doc, grade in zip(state["documents"], state["document_grades"])
        if grade == "relevant"
    ]
    # pairs each document with its grade and keeps only the ones marked relevant

    return "\n\n".join(f"[{doc['source']} p.{doc['page']}] {doc['text']}" for doc in relevant_docs)
    # tags each chunk with its source and page, so citations are possible


# 4. generate:
# This fourth node writes the actual answer. 
# It filters documents down to only the ones grade_documents marked "relevant"
# (pairing each doc with its matching grade via zip). It answers original_question, 
# not question — so even if the query got rewritten one or two times for better retrieval, 
# the final answer is always addressed to what the user actually asked.

GENERATE_SYSTEM_PROMPT = (
    "Answer the question using only the provided context documents. "
    "If the context doesn't contain the answer, say you don't have enough information."
    "Mention the source and page for any claim you make."
)

# grounds the answer in the retrieved chunks and discourages the model from making things up

def generate(state: GraphState) -> GraphState:
    # fourth node: writes the answer, using only the chunks that graded as relevant
    context = _relevant_context(state)

    user_prompt = f"Question: {state['original_question']}\nContext:\n{context}"
    # always answers the user's original question, not a rewritten search query

    chat_model = EuriChatModel()
    answer = chat_model(GENERATE_SYSTEM_PROMPT, user_prompt).strip()

    state["answer"] = answer
    # saves the draft answer so validate_answer can check it next
    return state


# 5. validate_answer():
# The self-correction from the second task spec. It doesn't recheck
# retrieval(grade_documents job); it judges itself on 4 parameters
# one structure call covers all four checks at once. then gets collapsed
# into a single "pass"/"fail" verdict. 
VALIDATE_SYSTEM_PROMPT = (
    "You review a generated answer against its source context. Check: " \
    "is the answer grounded in the context and not making things up, " \
    "what is the hallucination risk (low, medium, or high), " \
    "is the answer complete for the question asked, " \
    "and was the context too thin or off-topic to answer well. " \
    "Reply with Only a JSON object with these exact keys: "
    '"grounded" (true/false), "hallucination_risk" ("low"/"medium"/"high"), '
    '"complete" (true/false), "retrieval_insufficient" (true/false).'
)
# one call checks all four things the task asks for, in a single structured reply. 

def validate_answer(state: GraphState) -> GraphState:
    # fifth node: judges the answer itself, not just retrieval step
    context = _relevant_context(state)
    # same context generate() used, so the judge is checking against what the answer was built from
    
    user_prompt = f"Question: {state['original_question']}\nAnswer: {state['answer']}\nContext:\n{context}"

    chat_model = EuriChatModel()
    raw_reply = chat_model(VALIDATE_SYSTEM_PROMPT, user_prompt)
    # Models sometimes wrap JSON in Markdown fences or add a short sentence.
    # Extract the JSON object before parsing so the stream does not crash.
    cleaned_reply = raw_reply.strip()
    if cleaned_reply.startswith("```"):
        cleaned_reply = cleaned_reply.split("\n", 1)[-1]
        if cleaned_reply.endswith("```"):
            cleaned_reply = cleaned_reply[:-3].strip()

    try:
        result = json.loads(cleaned_reply)
    except json.JSONDecodeError:
        start = cleaned_reply.find("{")
        end = cleaned_reply.rfind("}")
        if start >= 0 and end > start:
            try:
                result = json.loads(cleaned_reply[start:end + 1])
            except json.JSONDecodeError:
                result = None
        else:
            result = None

    # A malformed judge response is treated as a failed validation attempt,
    # allowing the graph's bounded retry logic to continue normally.
    if not isinstance(result, dict):
        result = {
            "grounded": False,
            "hallucination_risk": "high",
            "complete": False,
            "retrieval_insufficient": False,
        }
    # result has keys: grounded, hallucination_risk, complete, retrieval_insufficient

    passed = result["grounded"] and result["complete"] and result["hallucination_risk"] == "low"
    result["verdict"] = "pass" if passed else "fail"
    # one combined verdict, so the conditional edge in graph.py has a single field to check

    state["validation"] = result
    state["validation_retries"] += 1
    # counts this attempt, so the conditional edge can enforce the max validation retry limit

    return state


def mark_resolved(state: GraphState) -> GraphState:
    # terminal node: reached when validate_answer passed
    state["status"] = "resolved"
    return state


def mark_unresolved(state: GraphState) -> GraphState:
    # terminal node: reached when retries ran out and the answer still didn't pass validation
    state["status"] = "unresolved"
    return state

