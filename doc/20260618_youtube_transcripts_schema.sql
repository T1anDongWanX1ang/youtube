-- YouTube Crypto Agent — Video Transcripts
-- Migration: 20260618_youtube_transcripts_schema
-- Description: Verbatim full transcript per video, decoupled from analysis so the
--   analysis step always reads a complete source-of-truth and re-runs never need to
--   re-transcribe. This is the fix for "model only analysed 10% of the content":
--   capture the whole transcript first, validate coverage, then analyse from text.
--
-- ADDITIVE: does NOT modify any existing youtube_crypto_* table.
--
-- The canonical sample below is PostgreSQL syntax (matches doc/20251121_youtube_crypto_schema.sql).
-- The runtime DB is Doris (MySQL protocol) — Doris equivalents are noted at the bottom.

CREATE TABLE IF NOT EXISTS youtube_crypto_video_transcripts (
    id BIGSERIAL PRIMARY KEY,

    -- Relationship to video (logical, no FK constraint)
    video_id TEXT NOT NULL UNIQUE,            -- YouTube video ID

    -- Transcript content
    language TEXT,                            -- detected original language, e.g. 'en'
    source TEXT NOT NULL DEFAULT 'gemini',    -- 'gemini' (v1) | reserved: 'caption' | 'asr'
    segments_json JSONB,                      -- [{"start": <seconds:int>, "text": "..."}]
    full_text TEXT NOT NULL,                  -- concatenated verbatim transcript

    -- Coverage metrics (gate before analysis)
    word_count INTEGER,                       -- total words across segments
    duration_covered_sec INTEGER,             -- last segment start (compare to video duration)
    coverage_ok BOOLEAN,                      -- TRUE if coverage met the threshold; analysis only reads TRUE

    -- LLM call metadata
    model_name TEXT,
    prompt_token_count INTEGER,
    candidates_token_count INTEGER,
    total_token_count INTEGER,
    elapsed_seconds DOUBLE PRECISION,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_yc_transcripts_video
    ON youtube_crypto_video_transcripts(video_id);

-- =====================================================
-- Doris (MySQL protocol) equivalent
-- =====================================================
-- CREATE TABLE youtube_crypto_video_transcripts (
--     id            BIGINT,
--     video_id      VARCHAR(64) NOT NULL,
--     language      VARCHAR(16),
--     source        VARCHAR(16) NOT NULL DEFAULT 'gemini',
--     segments_json TEXT,           -- JSON stored as TEXT
--     full_text     TEXT NOT NULL,
--     word_count    INT,
--     duration_covered_sec INT,
--     coverage_ok   BOOLEAN,
--     model_name    VARCHAR(128),
--     prompt_token_count     INT,
--     candidates_token_count INT,
--     total_token_count      INT,
--     elapsed_seconds        DOUBLE,
--     created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
--     updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
-- )
-- UNIQUE KEY(id, video_id)        -- or use video_id as the dedup key per Doris model
-- DISTRIBUTED BY HASH(video_id) BUCKETS 4
-- PROPERTIES ("replication_num" = "1");
