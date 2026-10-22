# InsightBridge

Saved customer support analysis from GPT-5.4 and GPT-6 Astra.
Live model calls are disabled. Original run logs and usage are retained separately from edited display copy.

Start: `python -m delayed_orders.ui --host 0.0.0.0`

Render disk: `/var/data`. Feedback, visits and key clicks are stored privately in
`/var/data/insightbridge/feedback/events.jsonl`, with UTC time, browser/session ID and IP address.
Access these records through the Render service Shell. The app has no public feedback-log endpoint.
Jira decisions remain in browser storage; Jira is not connected.
