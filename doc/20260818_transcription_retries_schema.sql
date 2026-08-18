-- Migration: bounded transcription retries and terminal skip reasons.
-- Run the section matching the database engine before deploying the worker.

-- PostgreSQL
ALTER TABLE youtube_crypto_videos
    ADD COLUMN IF NOT EXISTS transcription_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE youtube_crypto_videos
    ADD COLUMN IF NOT EXISTS transcription_last_error TEXT;
ALTER TABLE youtube_crypto_videos
    ADD COLUMN IF NOT EXISTS transcription_last_failed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_yc_videos_transcription_retries
    ON youtube_crypto_videos (analysis_status, transcription_attempts);

-- Doris (MySQL protocol). Use these statements instead of the PostgreSQL section
-- when applying directly to the runtime database.
-- ALTER TABLE youtube_crypto_videos
--     ADD COLUMN IF NOT EXISTS transcription_attempts INT DEFAULT 0;
-- ALTER TABLE youtube_crypto_videos
--     ADD COLUMN IF NOT EXISTS transcription_last_error TEXT;
-- ALTER TABLE youtube_crypto_videos
--     ADD COLUMN IF NOT EXISTS transcription_last_failed_at DATETIME;
