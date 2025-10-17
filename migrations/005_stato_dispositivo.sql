PRAGMA foreign_keys=OFF;
BEGIN;

ALTER TABLE devices ADD COLUMN status TEXT NOT NULL DEFAULT 'active';

UPDATE schema_version SET version = 5;
COMMIT;
PRAGMA foreign_keys=ON;