# Retrieval Packet Contract

`knowledge_retrieval.py` emits:

```json
{
  "task_goal": "string",
  "keywords": ["token"],
  "project": "optional-project",
  "date_range": {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"},
  "matched_daily": [],
  "matched_adrs": [],
  "matched_cards": [],
  "open_loops": [],
  "reuse_recommendations": []
}
```

Use the packet as the default preflight input for knowledge workflows.
