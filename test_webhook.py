"""
Test script for the Nistula webhook.
Run the server first: uvicorn main:app --reload
Then in another terminal: python test_webhook.py
"""

import httpx
import json

BASE_URL = "http://localhost:8000"

TEST_CASES = [
    {
        "label": "Test 1 — Availability + pricing query (pre-sales)",
        "payload": {
            "source": "whatsapp",
            "guest_name": "Rahul Sharma",
            "message": "Is the villa available from April 20 to 24? What is the rate for 2 adults?",
            "timestamp": "2026-05-05T10:30:00Z",
            "booking_ref": "NIS-2024-0891",
            "property_id": "villa-b1",
        },
    },
    {
        "label": "Test 2 — Post-sales check-in query",
        "payload": {
            "source": "booking_com",
            "guest_name": "Priya Mehta",
            "message": "Hi, what time can we check in? Also can you send the WiFi password please?",
            "timestamp": "2026-05-06T08:15:00Z",
            "booking_ref": "NIS-2024-1042",
            "property_id": "villa-b1",
        },
    },
    {
        "label": "Test 3 — Complaint (3am hot water)",
        "payload": {
            "source": "whatsapp",
            "guest_name": "James Whitfield",
            "message": "There is no hot water and we have guests arriving for breakfast in 4 hours. This is unacceptable. I want a refund for tonight.",
            "timestamp": "2026-05-07T03:00:00Z",
            "booking_ref": "NIS-2024-1187",
            "property_id": "villa-b1",
        },
    },
    {
        "label": "Test 4 — Special request via Airbnb",
        "payload": {
            "source": "airbnb",
            "guest_name": "Nadia Costa",
            "message": "We would love to arrange a private chef dinner for our anniversary on our second night. Is that possible?",
            "timestamp": "2026-05-08T14:00:00Z",
            "booking_ref": "NIS-2024-1201",
            "property_id": "villa-b1",
        },
    },
    {
        "label": "Test 5 — General enquiry, no booking ref",
        "payload": {
            "source": "instagram",
            "guest_name": "Sameer Khan",
            "message": "Do you allow pets? We have a small dog.",
            "timestamp": "2026-05-09T11:00:00Z",
            "property_id": "villa-b1",
        },
    },
]


def run_tests():
    print("=" * 60)
    print("NISTULA WEBHOOK TEST SUITE")
    print("=" * 60)

    with httpx.Client(timeout=60.0) as client:
        for tc in TEST_CASES:
            print(f"\n{tc['label']}")
            print("-" * 60)
            try:
                resp = client.post(f"{BASE_URL}/webhook/message", json=tc["payload"])
                if resp.status_code == 200:
                    data = resp.json()
                    print(f"  query_type     : {data['query_type']}")
                    print(f"  confidence     : {data['confidence_score']}")
                    print(f"  action         : {data['action']}")
                    print(f"  message_id     : {data['message_id']}")
                    print(f"\n  drafted_reply  :\n")
                    for line in data["drafted_reply"].split("\n"):
                        print(f"    {line}")
                else:
                    print(f"  ERROR {resp.status_code}: {resp.text}")
            except Exception as e:
                print(f"  EXCEPTION: {e}")

    print("\n" + "=" * 60)
    print("Tests complete.")


if __name__ == "__main__":
    run_tests()
