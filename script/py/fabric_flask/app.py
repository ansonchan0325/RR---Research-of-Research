import json
import uuid

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from flask import Flask, render_template, request, jsonify
import os
import random
from bing_search import ThesisTopicGenerator  # Import the thesis generator
from cosmos import CosmosDBClient  # Import the CosmosDBClient
from datetime import datetime, timezone, timedelta
from openai import OpenAI

COSMOS_URL = ''
COSMOS_KEY = ""
DATABASE_NAME = ''
CONTAINER_NAME = ''
PARTITION_KEY = ''  # Ensure this matches the partition key path in your Cosmos DB

USER_ID = ""

AZURE_SEARCH_SERVICE = ""
SEARCH_CLIENT = SearchClient(
    endpoint=AZURE_SEARCH_SERVICE,
    index_name="",
    credential=AzureKeyCredential("")
)
# Chat prompt template
GROUNDED_PROMPT = """
You are a friendly assistant that recommends papers.
The sources is from a report.
If there isn't enough information below, say you don't know.
Do not generate answers that don't use the sources below.
Query: {query}
Sources:\n{sources}
"""




# Initialize the CosmosDB client
cosmos_client_query = CosmosDBClient(
    url=COSMOS_URL,
    key=COSMOS_KEY,
    database_name=DATABASE_NAME,
    container_name=CONTAINER_NAME,
    partition_key=PARTITION_KEY
)

cosmos_client_query_metadata = CosmosDBClient(
    url=COSMOS_URL,
    key=COSMOS_KEY,
    database_name=DATABASE_NAME,
    container_name="query_metadata",
    partition_key=PARTITION_KEY
)
app = Flask(__name__)



@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if request.method == 'POST':
        data = request.get_json()
        user_query = data.get("query")
        show_sources = data.get('showSources', False)
        chat_history = data.get('chatHistory', [])

        context_text = ""
        if show_sources and chat_history:
            context_text = '\n'.join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in chat_history])

        search_results = SEARCH_CLIENT.search(
            search_text=user_query+context_text,
            top=5,
            select="title,authors,tldr,referenceCount,citationCount,pdf_url,summary,Tag_1,Tag_2,Tag_3,Tag_4,Tag_5,field"
        )
        sources = [
            dict(paper) for paper in search_results
        ]
        print(sources)
        prompt = GROUNDED_PROMPT.format(query=user_query, sources=sources)
        client = OpenAI(
            api_key="")
        response = client.chat.completions.create(
            model="",
            messages=[{
            "role": "user",
            "content": prompt
        }],
            max_tokens=500,  # Adjust as needed
            temperature=0.5,
            n=1
        )
        # response = openai.generate(prompt)
        return jsonify({'response': response.choices[0].message.content })
    else:
        return render_template('chat.html')


@app.route('/power_search', methods=['GET', 'POST'])
def power_search():
    if request.method == 'POST':
        data = request.get_json()
        query_text = data.get('query')
        session_id = data.get('id')
        date_from = data.get('date_from')
        date_to = data.get('date_to')

        # Enforce mutual exclusivity between query and id
        if query_text and session_id:
            return jsonify({'status': 'error', 'message': 'Please provide either a query or an ID, not both.'}), 400
        elif not query_text and not session_id:
            return jsonify({'status': 'error', 'message': 'Please provide a query or an ID.'}), 400

        # Proceed based on whether query or id is provided
        if session_id:
            # Use the existing session ID to perform search
            # Here, you would retrieve the session data from Cosmos DB and perform the search
            return jsonify({'status': 'success', 'message': f'Searching using session ID: {session_id}'})
        else:
            # Use the query text to perform a new search
            # Save the new search query to Cosmos DB if necessary
            return jsonify({'status': 'success', 'message': f'Searching using query: {query_text}'})
    else:
        return render_template('power_search.html')

@app.route('/query_submit', methods=['POST'])
@app.route('/query_submit', methods=['POST'])
def query_submit():
    # This route handles the search logic
    data = request.get_json()
    query_text = data.get('query')
    session_id = data.get('id')
    date_from = data.get('date_from')
    date_to = data.get('date_to')
    priority = data.get('priority')
    # Enforce mutual exclusivity between query and id
    if query_text and session_id:
        return jsonify({'status': 'error', 'message': 'Please provide either a query or an ID, not both.'}), 400
    elif not query_text and not session_id:
        return jsonify({'status': 'error', 'message': 'Please provide a query or an ID.'}), 400

    # Proceed based on whether query or id is provided
    if session_id:
        query_metadata = cosmos_client_query_metadata.query_documents(
            query=f"SELECT * FROM c WHERE c.id = '{session_id}'"
        )
        if not query_metadata:
            return jsonify({'status': 'error', 'message': 'Session not found.'}), 404

        query_list = query_metadata[0].get("selected_topics", [])
        query = [ t.split("|")[-1]  for layer in query_list for t in layer]
        ",".join(query)
        document_data = {
            "id": uuid.uuid4().hex,  # Generate a unique ID for the new query
            "user_id": USER_ID,
            "query_text": query,
            "date_from": date_from,
            "date_to": date_to,
            "priority": int(priority),
            "email" : "",
            "status": 0,

            "metadata": {
                "created_at": datetime.now(timezone.utc).isoformat(),  # Timestamp
                "updated_at":datetime.now(timezone.utc).isoformat(),
                "source": "user_input"  # Indicate the source as user input
            },
            "partitionKey": USER_ID  # Partition key for Cosmos DB
        }
        saved_document = cosmos_client_query.create_document(document_data)

        return jsonify({'status': 'success', 'message': f'Searching using session ID: {session_id}'})

    else:
        # Use the query text to perform a new search
        # Save the new search query to Cosmos DB in the 'query' container
        try:
            document_data = {
                "id": uuid.uuid4().hex,  # Generate a unique ID for the new query
                "user_id": USER_ID,
                "query_text": query_text,
                "date_from": date_from,
                "date_to": date_to,
                "priority": int(priority),
                "status": 0,
                "metadata": {
                    "created_at": datetime.now(timezone.utc).isoformat(),  # Timestamp
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "source": "user_input",  # Indicate the source as user input
                },
                "partitionKey": USER_ID  # Partition key for Cosmos DB
            }

            # Save the document to the 'query' container
            saved_document = cosmos_client_query.create_document(document_data)

            if saved_document:
                return jsonify({'status': 'success', 'message': 'Query saved to Cosmos DB.'})
            else:
                return jsonify({'status': 'error', 'message': 'Failed to save query to Cosmos DB.'}), 500
        except Exception as e:
            print(f"Error saving query: {e}")
            return jsonify({'status': 'error', 'message': 'An error occurred while saving query.'}), 500
@app.route('/check_id', methods=['POST'])
def check_id():
    data = request.get_json()
    session_id = data.get('id')
    user_id = USER_ID  # Replace with dynamic user ID if applicable

    # Query Cosmos DB to check if the ID exists
    try:
        document = cosmos_client_query_metadata.query_documents(
            query=f"SELECT * FROM c WHERE c.id = '{session_id}' AND c.user_id = '{user_id}'"
        )
        if document:
            # ID exists
            return jsonify({'status': 'success', 'message': 'ID exists in Cosmos DB.'})
        else:
            # ID does not exist
            return jsonify({'status': 'error', 'message': 'Query metadata not exists.'}), 404
    except Exception as e:
        print(f"Error checking ID: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred while checking ID.'})
@app.route('/metadata_store', methods=['GET'])
def view_history():
    user_id = USER_ID  # Replace with dynamic user ID logic if available
    query = f"SELECT * FROM c WHERE c.user_id = '{user_id}'"
    user_sessions = cosmos_client_query_metadata.query_documents(query)  # Fetch all documents for the user

    # Sort sessions by timestamp if needed
    user_sessions = sorted(user_sessions, key=lambda x: x['metadata']['created_at'], reverse=True)

    # Process sessions to calculate expiration date and status text
    for session in user_sessions:
        created_at = datetime.fromisoformat(session['metadata']['created_at'])
        expired_at = created_at + timedelta(seconds=2592000)  # 30 days in seconds
        session['expired_date'] = expired_at.strftime("%Y-%m-%d %H:%M:%S")
        session['created_at'] = created_at.strftime("%Y-%m-%d %H:%M:%S")


    return render_template('metadata_store.html', sessions=user_sessions)



@app.route('/metadata', methods=['GET', 'POST'])
def metadata():
    if request.method == 'POST':
        # Check if the request is an AJAX call by checking for 'selected_topics'
        selected_topics = request.form.getlist('selected_topics')
        selected_subtopics = request.form.get('selected_subtopics')
        if selected_subtopics:
            selected_subtopics = json.loads(selected_subtopics)
        else:
            selected_subtopics = []
        if selected_topics:
            # This is an AJAX request from addNextLayer()
            search_query = request.form.get('search_query')
            search_engine = request.form.get('search_engine')
            recursive_depth = int(request.form.get('recursive_depth'))
            current_depth = int(request.form.get('current_depth', 1))

            # Increment current depth
            current_depth += 1

            if current_depth > recursive_depth:
                return jsonify({'error': 'Maximum recursive depth reached.'}), 400

            # Generate new topics based on selected topics
            new_topics = []

            for topic in selected_topics:
                generator= ThesisTopicGenerator(query=topic,max_depth=1,num_new_tags=10//len(selected_topics))
                gen_topics = generator.run()
                new_topics.extend([f"{topic} | {g}" for g in gen_topics])
                # test code
                # new_topics.extend([f"{topic} | subtopic {g}" for g in range(10//len(selected_topics))])

            # Return JSON response
            return jsonify({
                'new_topics': new_topics,
                'current_depth': current_depth
            })
        else:
            # This is the initial form submission
            search_query = request.form.get('search_query')
            search_engine = request.form.get('search_engine')
            recursive_depth = int(request.form.get('recursive_depth', 1))
            current_depth = 1
            generator = ThesisTopicGenerator(query=search_query, max_depth=1, num_new_tags=10)
            gen_topcis = generator.run()
            # Generate initial topics
            new_topics = gen_topcis
            # new_topics = [f"Topic {i}" for i in range(1, 11)]

            # Render the template with initial data
            return render_template('metadata.html',
                                   search_query=search_query,
                                   search_engine=search_engine,
                                   recursive_depth=recursive_depth,
                                   current_depth=current_depth,
                                   top_topics=new_topics)
    else:
        # Handle GET request
        return render_template('metadata.html')


@app.route('/save_topics', methods=['POST'])
def save_topics():

    data = request.get_json()
    all_topics = data.get('allTopics', [])
    selected_topics = data.get('layers', [])
    print(all_topics)
    print(selected_topics)
    # Document data structure for saving both all generated topics and selected topics
    ttl = 60 * 60 * 24 * 30  # 30 days in seconds
    document_data = {"id": uuid.uuid5(uuid.NAMESPACE_DNS, f"{USER_ID}-{datetime.now()}").hex,
                     "user_id": USER_ID, "all_topics": all_topics, "selected_topics": selected_topics,
                     "topic_count": len(selected_topics), "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),  # Timestamp
            "source": "app_generated",  # Source of data (e.g., user_input or app_generated)
            "version": 1,  # Version for schema or structure changes
            "expired_at": datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + 2592000, tz=timezone.utc).isoformat()
        }, "partitionKey": USER_ID, 'ttl': ttl}

    # Save to Cosmos DB using the CosmosDBClient
    saved_document = cosmos_client_query_metadata.create_document(document_data)

    if saved_document:
        return jsonify({'status': 'success', 'message': 'Topics saved to Cosmos DB.'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to save topics to Cosmos DB.'}), 500

@app.route('/update', methods=['POST'])
def update_topics():
    data = request.get_json()
    session_id = data.get('id')  # The ID of the session to update
    print(session_id)
    user_id = USER_ID  # Use dynamic user_id logic if needed
    all_topics = data.get('allTopics', [])
    selected_topics = data.get('layers', [])

    # Query the document to update based on session ID and user ID
    try:
        document = cosmos_client_query_metadata.query_documents(
            query=f"SELECT * FROM c WHERE c.id = '{session_id}'"
        )
        if not document:
            return jsonify({'status': 'error', 'message': 'Session not found.'}), 404
        print(document)
        # Modify document data with updated information
        updated_document = document[0]  # Assume a single document is returned
        print(updated_document)
        updated_document['all_topics'] = all_topics
        updated_document['selected_topics'] = selected_topics
        updated_document['topic_count'] = len(selected_topics)

        # Update metadata
        updated_document['metadata']['version'] += 1  # Increment version
        updated_document['metadata']['updated_at'] = datetime.now(timezone.utc).isoformat()
        updated_document['metadata']['expired_at'] = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

        # Save updated document back to Cosmos DB
        saved_document = cosmos_client_query_metadata.upsert_document(updated_document)

        if saved_document:
            return jsonify({'status': 'success', 'message': 'Topics updated successfully in Cosmos DB.'})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to update topics in Cosmos DB.'}), 500

    except Exception as e:
        print(f"Error updating session: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred during update.'}), 500


@app.route('/delete_session/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    try:


        # Query the document by its ID
        document = cosmos_client_query_metadata.query_documents(
            query=f"SELECT * FROM c WHERE c.id = '{session_id}'",
        )

        # Check if document exists
        if not document:
            return jsonify({"success": False, "message": "Session not found"}), 404

        # Delete the document
        cosmos_client_query_metadata.delete_document(document[0]['id'], document[0]['user_id'])  # Pass partition key value if needed

        return jsonify({"success": True, "message": "Session deleted successfully"})

    except Exception as e:
        print(f"Error deleting session: {e}")
        return jsonify({"success": False, "message": "Error deleting session"}), 500



if __name__ == '__main__':
    # Set debug=False in production
    app.run(debug=True)