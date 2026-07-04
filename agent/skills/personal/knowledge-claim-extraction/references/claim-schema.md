# Claim Packet Contract

`claim_extraction.py` emits:

```json
{
  "target_date": "YYYY-MM-DD",
  "include_chat": true,
  "claim_packets": [],
  "evidence_links": [],
  "promotion_suggestions": []
}
```

`claim_type` values:

- `fact`
- `decision`
- `action`
- `risk`
- `open_loop`
- `insight_candidate`
