# Part 3 — Thinking Question

**Scenario**: 3am. A guest at Villa B1 sends a WhatsApp message: "There is no hot water and we have guests arriving for breakfast in 4 hours. This is unacceptable. I want a refund for tonight."

---

## Question A — The Immediate Response

**The AI sends this now:**

>Hello [Guest name], I am truly sorry that there is no hot water at 3am – that’s just terrible, especially when we have guests arriving. We’ll be contacting our caretaker immediately and somebody will contact you within the next 15 minutes. This situation will definitely be sorted out. If you do not hear back from us by 3:20am, please contact [caretaker number].

**Why this wording:**  
The first line acknowledges the emotion felt by the guest without resorting to sucking up to the guest. For guests who feel bad, they have to be shown that we've heard what they've said before anything useful can be conveyed. The second line provides both an action item (contacting a caretaker) and a clear time frame (15 minutes). The line mentions a number because we are not behind a bot anymore; there is someone who will be held accountable.

The issue of the refund has been put off deliberately. It would be very risky to commit to a refund in the middle of the night without human involvement.

---

## Question B — The System Design

Beyond sending the message, the platform does the following simultaneously:

1. **Classify and flag**: The message is tagged `complaint` and `action = escalate`. It bypasses the AI auto-send queue entirely.

2. **Alert the caretaker**: A WhatsApp/SMS is sent to the caretaker on duty with the guest's name, villa, and the nature of the complaint. The platform logs the notification timestamp.

3. **Alert the on-call manager**: A push notification and SMS reaches a Nistula team member. The complaint is surfaced in the agent dashboard with a 15-minute SLA timer visible.

4. **Log everything**: Message, timestamp, AI draft, escalation trigger, all notification attempts — stored in the messages and conversations tables with `query_type = complaint` and `status = escalated`.

5. **30-minute no-response escalation**: If no agent marks the conversation as acknowledged in the dashboard within 30 minutes, the system sends a second alert to the manager's personal mobile, escalates the conversation status to `critical`, and sends the guest a follow-up message: *"We want to make sure you've been reached — has our caretaker contacted you yet?"* This both checks on the guest and creates gentle pressure on the team.

6. **Refund flag**: A `pending_refund_review` tag is attached to the reservation record for the duty manager to action in the morning.

---

## Question C — The Learning

After the third hot water complaint at Villa B1 in two months, the system should treat this as a **property maintenance pattern**, not a guest relations issue.

**Immediate action (automated):**  
The `property_complaint_patterns` materialised view surfaces this cluster. When the threshold (e.g. 2+ complaints on the same topic within 90 days) is crossed, the platform creates a maintenance ticket assigned to the property manager — not just a notification — with the complaint timestamps and message excerpts attached as evidence.

**What I would build to prevent complaint #4:**

A pre-stay infrastructure checklist workflow. 48 hours before every check-in, the caretaker receives a structured WhatsApp checklist: *"Please confirm: ✅ Hot water working ✅ AC tested ✅ Pool clean."* Responses are logged. If the hot water item is not confirmed by 6 hours before check-in, the duty manager is automatically notified.

The pattern detection layer also recommends a maintenance inspection. After two complaints of the same type, the system prompts: *"Villa B1 has had 3 hot water complaints since March. Flag for plumber inspection before next booking?"* — a one-tap action for the property manager.

The underlying insight is that complaint patterns are a maintenance signal masquerading as a guest relations problem. The platform should route them to the right person (the property manager, not the guest relations team) with enough evidence to act before the next guest arrives.
