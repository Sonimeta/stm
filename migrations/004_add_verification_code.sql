PRAGMA foreign_keys=OFF;
BEGIN;

-- 1) aggiungi la colonna senza vincoli (idempotente se già presente: il tuo runner lo gestisce)
ALTER TABLE verifications ADD COLUMN verification_code TEXT;

-- 2) (opzionale ma consigliato) normalizza eventuali duplicati o stringhe vuote
--    Se temi duplicati, puoi azzerarli prima di creare l’indice:
UPDATE verifications
SET verification_code = NULL
WHERE verification_code = '' OR verification_code IN (
  SELECT verification_code FROM verifications
  WHERE verification_code IS NOT NULL AND verification_code <> ''
  GROUP BY verification_code HAVING COUNT(*) > 1
);
-- );

-- 3) crea un indice UNIQUE parziale (consente più NULL)
CREATE UNIQUE INDEX IF NOT EXISTS idx_verifications_verification_code_unique
ON verifications(verification_code)
WHERE verification_code IS NOT NULL AND verification_code <> '';


UPDATE schema_version SET version = 4;
COMMIT;
PRAGMA foreign_keys=ON;