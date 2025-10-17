PRAGMA foreign_keys=OFF;
BEGIN;

-- customers
ALTER TABLE customers ADD COLUMN uuid TEXT;
ALTER TABLE customers ADD COLUMN last_modified TEXT;
ALTER TABLE customers ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0;
ALTER TABLE customers ADD COLUMN is_synced INTEGER NOT NULL DEFAULT 0;

-- devices
ALTER TABLE devices ADD COLUMN uuid TEXT;
ALTER TABLE devices ADD COLUMN last_modified TEXT;
ALTER TABLE devices ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0;
ALTER TABLE devices ADD COLUMN is_synced INTEGER NOT NULL DEFAULT 0;
-- unique parziale su serial_number (SQLite: via indice filtrato simulato)
CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_serial_unique
ON devices(serial_number)
WHERE serial_number IS NOT NULL AND serial_number <> '';

-- verifications
ALTER TABLE verifications ADD COLUMN uuid TEXT;
ALTER TABLE verifications ADD COLUMN last_modified TEXT;
ALTER TABLE verifications ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0;
ALTER TABLE verifications ADD COLUMN is_synced INTEGER NOT NULL DEFAULT 0;

-- mti_instruments
ALTER TABLE mti_instruments ADD COLUMN uuid TEXT;
ALTER TABLE mti_instruments ADD COLUMN last_modified TEXT;
ALTER TABLE mti_instruments ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mti_instruments ADD COLUMN is_synced INTEGER NOT NULL DEFAULT 0;

UPDATE schema_version SET version = 2;
COMMIT;
PRAGMA foreign_keys=ON;