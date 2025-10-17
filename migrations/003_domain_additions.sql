PRAGMA foreign_keys=OFF;
BEGIN;

-- 1) VERIFICATIONS: colonna technician_username
ALTER TABLE verifications ADD COLUMN IF NOT EXISTS technician_username TEXT;

-- 2) SIGNATURES: tabella completa (incluso is_synced)
CREATE TABLE IF NOT EXISTS signatures (
    username TEXT PRIMARY KEY NOT NULL,
    signature_data BLOB,
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0
);

-- 3) PROFILES + PROFILE_TESTS
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    profile_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS profile_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    profile_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    parameter TEXT,
    limits_json TEXT,
    is_applied_part_test INTEGER NOT NULL DEFAULT 0,
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (profile_id) REFERENCES profiles (id) ON DELETE CASCADE
);

-- 4) DESTINATIONS + adeguamenti DEVICES
CREATE TABLE IF NOT EXISTS destinations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    address TEXT,
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0
);

-- Se la tua tabella devices deriva da v001/v002, ora le aggiungiamo/adeguiamo le colonne
ALTER TABLE devices ADD COLUMN IF NOT EXISTS destination_id INTEGER REFERENCES destinations(id);
ALTER TABLE devices ADD COLUMN IF NOT EXISTS department TEXT;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS default_profile_key TEXT;

-- (Facoltativo) se devices ha ancora customer_id, ricrea come in 017 per rimuoverlo
-- Controllo/ricreazione "safe" (puoi farlo se sai che esiste ancora customer_id)
CREATE TABLE devices_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    destination_id INTEGER REFERENCES destinations(id),
    serial_number TEXT,
    description TEXT,
    manufacturer TEXT,
    model TEXT,
    department TEXT,
    applied_parts_json TEXT,
    customer_inventory TEXT,
    ams_inventory TEXT,
    default_profile_key TEXT,
    verification_interval INTEGER,
    next_verification_date TEXT,
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0
);

-- 2. Copia tutti i dati dalla vecchia tabella a quella nuova, omettendo la colonna 'customer_id'
INSERT INTO devices_new (
    id, uuid, destination_id, serial_number, description, manufacturer, model, department,
    applied_parts_json, customer_inventory, ams_inventory, verification_interval,
    next_verification_date, last_modified, is_synced, is_deleted
)
SELECT
    id, uuid, destination_id, serial_number, description, manufacturer, model, department,
    applied_parts_json, customer_inventory, ams_inventory, verification_interval,
    next_verification_date, last_modified, is_synced, is_deleted
FROM devices;

-- 3. Cancella la vecchia tabella 'devices'
DROP TABLE devices;

-- 4. Rinomina la nuova tabella con il nome originale
ALTER TABLE devices_new RENAME TO devices;
-- Fine (aggiorna versione)
UPDATE schema_version SET version = 3;
COMMIT;
PRAGMA foreign_keys=ON;