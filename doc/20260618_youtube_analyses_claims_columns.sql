-- YouTube Crypto Agent — claim-level analysis columns
-- Migration: 20260618_youtube_analyses_claims_columns
-- Description: Additive columns on youtube_crypto_video_analyses for claim-level analysis.
--   ADDITIVE ONLY — existing columns (summary_*, sentiment, key_tokens, key_narratives,
--   conviction_score, risk_score, ...) are untouched so the consumer's facts.consensus
--   module keeps working.
--
-- PostgreSQL sample (runtime DB is Doris; notes at bottom).

ALTER TABLE youtube_crypto_video_analyses ADD COLUMN IF NOT EXISTS speaker TEXT;
ALTER TABLE youtube_crypto_video_analyses ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE youtube_crypto_video_analyses ADD COLUMN IF NOT EXISTS is_substantive BOOLEAN;
ALTER TABLE youtube_crypto_video_analyses ADD COLUMN IF NOT EXISTS overall_thesis TEXT;
ALTER TABLE youtube_crypto_video_analyses ADD COLUMN IF NOT EXISTS claims_json JSONB;
ALTER TABLE youtube_crypto_video_analyses ADD COLUMN IF NOT EXISTS events_referenced_json JSONB;
ALTER TABLE youtube_crypto_video_analyses ADD COLUMN IF NOT EXISTS catalysts_json JSONB;
ALTER TABLE youtube_crypto_video_analyses ADD COLUMN IF NOT EXISTS risks_json JSONB;

-- =====================================================
-- Doris (MySQL protocol) equivalent
-- =====================================================
-- ALTER TABLE youtube_crypto_video_analyses ADD COLUMN speaker VARCHAR(255);
-- ALTER TABLE youtube_crypto_video_analyses ADD COLUMN category VARCHAR(32);
-- ALTER TABLE youtube_crypto_video_analyses ADD COLUMN is_substantive BOOLEAN;
-- ALTER TABLE youtube_crypto_video_analyses ADD COLUMN overall_thesis TEXT;
-- ALTER TABLE youtube_crypto_video_analyses ADD COLUMN claims_json TEXT;             -- JSON as TEXT
-- ALTER TABLE youtube_crypto_video_analyses ADD COLUMN events_referenced_json TEXT;
-- ALTER TABLE youtube_crypto_video_analyses ADD COLUMN catalysts_json TEXT;
-- ALTER TABLE youtube_crypto_video_analyses ADD COLUMN risks_json TEXT;
