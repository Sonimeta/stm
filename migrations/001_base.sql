PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER NOT NULL
);

INSERT INTO schema_version(version) SELECT 1
WHERE NOT EXISTS(SELECT 1 FROM schema_version);

-- customers (SENZA UNIQUE su name)
CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  address TEXT,
  phone TEXT,
  email TEXT
);

-- devices (serial_number NULLABLE)
CREATE TABLE IF NOT EXISTS devices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
  serial_number TEXT,
  description TEXT,
  manufacturer TEXT,
  model TEXT,
  applied_parts_json TEXT,
  customer_inventory TEXT,
  ams_inventory TEXT,
  default_profile_key TEXT,
  next_verification_date TEXT,
  verification_interval INTEGER
);

-- verifications (già con colonne extra)
CREATE TABLE IF NOT EXISTS verifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  verification_date TEXT NOT NULL,
  profile_name TEXT NOT NULL,
  results_json TEXT NOT NULL,
  overall_status TEXT NOT NULL,
  visual_inspection_json TEXT,
  mti_instrument TEXT,
  mti_serial TEXT,
  mti_version TEXT,
  mti_cal_date TEXT,
  technician_name TEXT
);

-- mti_instruments
CREATE TABLE IF NOT EXISTS mti_instruments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  instrument_name TEXT NOT NULL,
  serial_number TEXT NOT NULL,
  fw_version TEXT,
  calibration_date TEXT,
  is_default INTEGER NOT NULL DEFAULT 0
);

UPDATE schema_version SET version = 1;