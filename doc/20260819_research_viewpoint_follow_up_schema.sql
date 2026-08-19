-- Doris / MySQL-protocol runtime migration.
-- research_viewpoint already has source_url; only follow_up is new.
ALTER TABLE research_viewpoint
    ADD COLUMN follow_up TEXT;
