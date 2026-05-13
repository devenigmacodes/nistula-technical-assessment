# Nistula-technical-assessment
A guest message handler for Nistula’s platform. Uses a webhook to receive incoming messages, normalises them, classifies the type of query, drafts a reply through Claude and returns a confidence scored response with an action recommendation
**Requirements**: Python 3.11+
## Architecture
Inbound Webhook  
->Payload Validation  
-> Message Normalisation  
-> Query Classification  
-> Claude Draft Generation  
->Confidence Scoring  
->Action Routing

## setup 
# 1. Create and activate a virtual environment
```bash
python -m venv venv
source venv/bin/activate
```
# 2. Install dependencies
   ```bash
pip install -r requirements.txt
```
# 3. Configure environment
  ```bash
  cp .env.example .env
```
Create a .env file: ANTHROPIC_API_KEY=your_api_key_here
              **change .env and supply your own ANTHROPIC_API_KEY.**
# 4. Run the server 
 ```bash
uvicorn main:app --reload
```
   Server runs at: 
    http://localhost:8000
  ## Testing
  With the server running,  we will open a second terminal:
  ```bash
  python test_webhook.py
```
  # This runs 5 test cases covering: pre sales availability, check-in queries, a 3am complaint, a special request and a general enquiry with no booking reference.
**or test manually with curl**
```bash
curl -X POST http://localhost:8000/webhook/message \
  -H "Content-Type: application/json" \
  -d '{
    "source": "whatsapp",
    "guest_name": "Rahul Sharma",
    "message": "Is the villa available from April 20 to 24? What is the rate for 2 adults?",
    "timestamp": "2026-05-05T10:30:00Z",
    "booking_ref": "NIS-2024-0891",
    "property_id": "villa-b1"
  }'
```

interactive API docs: `http://localhost:8000/docs`
## How Confidence Scoring Works

| Signal | Weight |
|---|---|
| Query type | 40% |
| Property context available | 25% |
| Message clarity | 20% |
| Booking reference present | 15% |


### Query type scores

| Query Type | Score | Reasoning |
|---|---|---|
| `post_sales_checkin` | 0.95 | WiFi passwords and check-in times are facts  |
| `pre_sales_availability` | 0.90 | Availability is a yes/no from our data sheet |
| `pre_sales_pricing` | 0.88 | Pricing formula is fixed; only guest count varies |
| `general_enquiry` | 0.80 | Usually answerable but not always clear |
| `special_request` | 0.70 | Requires human confirmation (chef, airport transfers) |
| `complaint` | 0.45 | Needs empathy, judgment, and often a human decision |
### Action thresholds

Score: ≥ 0.85
Action: auto_send

Score: 0.60 – 0.84
Action: agent_review

Score: < 0.60
Action:  escalate

### Important Safety Rule 
Complaints are always escalated regardless of score to avoid unsupervised AI handling of sensitive guest situations.

### Design Decisions

I chose deterministic keyword classification instead of AI-based classification because it is:
* Faster
* Explainable
* Easier to debug
* Lower latency
* More predictable
  
A production system could later replace this with a lightweight ML classifier.
# Property Context Injection
 Rather than a RAG setup, mock property data is passed directly in the user prompt.
 * simple architecture 
 * can be replaced by a database 
 * response is structured
# Complaint Escalation Policy
This is  a product safety decision designed to reduce hospitality and brand risk in emotionally sensitive scenarios.
# A guest who is upset and receives an AI-generated response without a human ever seeing it is a brand risk. The system prioritises safety over throughput for negative sentiment

### Error Handling

The service handles:

* Invalid payloads
* Missing environment variables
* Claude API failures
* Timeout scenarios
* Internal exceptions

All failures return structured HTTP responses.
### Database Schema

schema.sql contains:
* Guest profiles
* Unified conversations
* Message storage
* AI draft tracking
* Confidence scores
* Incident escalation support
##  Project Structure
```
nistula-technical-assessment/
├── src/
│   ├── main.py           # FastAPI app — webhook,classifier,confidence scorer
│   └── test_webhook.py   # 5 test cases
├── schema.sql            # Part 2 — PostgreSQL schema with design 
├── thinking.md           # Part 3 — written answers
├── requirements.txt
├── .env.example
└── README.md
```
###   Part 3 Thinking

thinking.md contains:
* 3am operational complaint handling
* Escalation workflow design
* Learning and preventive maintenance strategy

  
 # Future Improvements
  * Multilingual support
  * Human feedback learning loop
  * Real-time analytics dashboard
 
###  Author
**Devansh Kumar Yaduvanshi**
      (Built as part of the Nistula Technical Assessment.)
 






