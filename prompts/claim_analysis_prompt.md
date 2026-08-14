You extract prediction-market evidence from one transcript chunk.
Return ONE complete JSON object only. No markdown. No prose outside JSON.

Required JSON shape:
{
  "speaker": "",
  "category": "market|economy|politics|world|business_tech|sports|other",
  "is_substantive": true,
  "overall_thesis": "one short sentence",
  "sentiment": "bullish|bearish|neutral|mixed",
  "conviction_score": 0,
  "risk_score": 0,
  "assets": [],
  "key_tokens": [],
  "narratives": [],
  "key_narratives": [],
  "events_referenced": [],
  "summary_brief": "one short sentence",
  "summary_detailed": "max 2 short sentences",
  "summary_full": "max 3 short sentences",
  "claims": [
    {
      "claim_text": "one falsifiable assertion",
      "type": "price_target|directional|macro|narrative|catalyst|risk|recommendation",
      "asset": "",
      "direction": "bullish|bearish|neutral",
      "target": "",
      "timeframe": "",
      "conditions": "",
      "reasoning": "one short sentence",
      "evidence_cited": [],
      "conviction": "low|medium|high",
      "verbatim_quote": "short exact quote",
      "timestamp": "",
      "how_to_verify": "one short sentence"
    }
  ],
  "catalysts_mentioned": [],
  "risks_mentioned": []
}

Rules:
- Use only this chunk.
- Extract at most the max claims in the chunk contract. If nothing concrete, use claims=[].
- Keep arrays to at most 5 items.
- Keep every string short. Total JSON must be under 1200 words.
- assets and key_tokens must match. narratives and key_narratives must match.
