-- Runtime migration for Doris (MySQL protocol).
-- Apply this file once before restarting the worker.

ALTER TABLE youtube_crypto_videos
    ADD COLUMN IF NOT EXISTS transcription_attempts INT DEFAULT 0;

ALTER TABLE youtube_crypto_videos
    ADD COLUMN IF NOT EXISTS transcription_last_error TEXT;

ALTER TABLE youtube_crypto_videos
    ADD COLUMN IF NOT EXISTS transcription_last_failed_at DATETIME;
