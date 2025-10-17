# database.py (Versione aggiornata con Gestore di Contesto)
import sqlite3
import json
import os
import logging
from datetime import datetime, timezone
import re
import serial
from app import config
from app.data_models import VerificationProfile, Test, Limit
import uuid

IGNORABLE_ERROR_SNIPPETS = (
    "duplicate column name",
    "already exists",
    "no such savepoint",  # difensivo
)

DB_PATH = config.DB_PATH
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ==============================================================================
# SEZIONE 1: GESTORE DI CONTESTO PER LA CONNESSIONE AL DATABASE
# ==============================================================================

class DatabaseConnection:
    """
    Un gestore di contesto robusto per la connessione al database SQLite.
    Gestisce automaticamente l'apertura, la chiusura, il commit e il rollback.
    """
    def __init__(self, db_name=DB_PATH):
        self.db_name = db_name
        self.conn = None

    def __enter__(self):
        """Metodo chiamato quando si entra nel blocco 'with'."""
        try:
            self.conn = sqlite3.connect(self.db_name)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON;")
            logging.info("Connessione al database aperta.")
            return self.conn
        except sqlite3.Error as e:
            logging.error(f"Errore di connessione al database: {e}", exc_info=True)
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Metodo chiamato quando si esce dal blocco 'with'."""
        if exc_type:
            logging.warning(f"Si è verificata un'eccezione, transazione DB annullata (rollback). Errore: {exc_val}")
            if self.conn is not None:
                self.conn.rollback()
        else:
            logging.info("Transazione DB completata, modifiche confermate (commit).")
            if self.conn is not None:
                self.conn.commit()
        
        if self.conn is not None:
            self.conn.close()
        logging.info("Connessione al database chiusa.")
        return False # Non sopprime eventuali eccezioni

# ==============================================================================
# SEZIONE 2: MIGRAZIONE DEL DATABASE
# ==============================================================================

def _execute_sql_script_compat(conn, sql_script: str) -> None:
    """
    Esegue uno script SQL rendendolo compatibile con versioni SQLite
    che non supportano 'ADD COLUMN IF NOT EXISTS'.
    - Rimuove 'IF NOT EXISTS' solo nei contesti 'ADD COLUMN'
    - Esegue statement singolarmente
    - Ignora errori idempotenti (colonna già esistente / oggetto già esistente)
    """
    # 1) normalizza gli 'ADD COLUMN IF NOT EXISTS' -> 'ADD COLUMN'
    script = re.sub(
        r'(?i)(ADD\s+COLUMN)\s+IF\s+NOT\s+EXISTS',
        r'\1',
        sql_script,
    )

    # 2) split molto semplice per ';' (gli script di migrazione sono lineari)
    statements = [s.strip() for s in script.split(';') if s.strip()]
    cur = conn.cursor()
    for stmt in statements:
        try:
            cur.execute(stmt)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if any(snippet in msg for snippet in IGNORABLE_ERROR_SNIPPETS):
                logging.info(f"[migrate] Ignoro statement già applicato: {stmt[:120]}... ({e})")
                continue
            logging.warning(f"[migrate] Errore eseguendo: {stmt}\n→ {e}")
            raise
    cur.close()

def migrate_database():
    """Applica le migrazioni SQL al database in modo sequenziale."""
    migrations_path = os.path.join(config.BASE_DIR, 'migrations') 
    if not os.path.isdir(migrations_path):
        logging.info(f"Cartella delle migrazioni '{migrations_path}' non trovata. Migrazione saltata.")
        return

    try:
        with DatabaseConnection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);")
            result = conn.execute("SELECT version FROM schema_version;").fetchone()
            current_version = result['version'] if result else 0
        
        migration_files = sorted([f for f in os.listdir(migrations_path) if f.endswith('.sql')])

        for m_file in migration_files:
            try:
                file_version = int(m_file.split('_')[0])
            except (ValueError, IndexError):
                logging.warning(f"File di migrazione '{m_file}' non nominato correttamente. Ignorato.")
                continue

            if file_version > current_version:
                logging.info(f"Applicando migrazione: {m_file}...")
                with open(os.path.join(migrations_path, m_file), 'r', encoding='utf-8') as f:
                    sql_script = f.read()
                
                with DatabaseConnection() as conn:
                    try:
                        _execute_sql_script_compat(conn, sql_script)
                    except Exception:
                        logging.critical("Errore critico durante la migrazione del database.", exc_info=True)
                        raise
                    # Aggiorna la versione dello schema
                    if current_version == 0 and file_version == 1:
                        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (file_version,))
                    else:
                        conn.execute("UPDATE schema_version SET version = ?", (file_version,))
                
                current_version = file_version
                logging.info(f"Database aggiornato alla versione {current_version}.")
    except Exception as e:
        logging.critical("Errore critico durante la migrazione del database.", exc_info=True)
        raise

# ==============================================================================
# SEZIONE 3: FUNZIONI DI MANIPOLAZIONE DATI (DAO)
# ==============================================================================

# --- Helper per decodifica JSON ---
def _decode_json_fields(row, fields_to_decode):
    if not row: return None
    data = dict(row)
    for field in fields_to_decode:
        json_string = data.get(field)
        new_key = field.replace('_json', '')
        try:
            data[new_key] = json.loads(json_string) if json_string else []
        except (json.JSONDecodeError, TypeError):
            data[new_key] = []
    return data

# --- Gestione Dispositivi (Devices) ---

def find_device_by_serial(serial_number: str, include_deleted: bool = False):
    """
    Trova un dispositivo per matricola (solo attivi).
    Se include_deleted=True, cerca anche tra i record eliminati.
    """
    if not serial_number: return None
    with DatabaseConnection() as conn:
        query = "SELECT * FROM devices WHERE serial_number = ? AND status = 'active'" # Filtra per attivi
        params = [serial_number]
        if not include_deleted:
            query += " AND is_deleted = 0"
        
        row = conn.execute(query, tuple(params)).fetchone()
        return _decode_json_fields(row, ['applied_parts_json']) if row else None

def add_device(uuid, destination_id, serial, desc, mfg, model, department, applied_parts, customer_inv, ams_inv, verification_interval, default_profile_key, timestamp):
    
    pa_json = json.dumps([pa if isinstance(pa, dict) else pa.__dict__ for pa in applied_parts])
    interval = int(verification_interval) if verification_interval not in [None, "Nessuno"] else None
    
    with DatabaseConnection() as conn:
        query = """
            INSERT INTO devices (
                uuid, destination_id, serial_number, description, manufacturer, 
                model, department, applied_parts_json, customer_inventory, 
                ams_inventory, verification_interval, default_profile_key,
                last_modified, is_synced, is_deleted, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'active')
        """
        params = (
            uuid, destination_id, serial, desc, mfg, model, department, pa_json, 
            customer_inv, ams_inv, interval, default_profile_key, timestamp
        )
        conn.execute(query, params)

def update_device(
    dev_id, destination_id, serial, desc, mfg, model, department,
    applied_parts, customer_inv, ams_inv,
    verification_interval, default_profile_key, timestamp,
    reactivate=False, new_destination_id=None):

    final_destination_id = new_destination_id if new_destination_id is not None else destination_id
    pa_json = json.dumps([pa if isinstance(pa, dict) else pa.__dict__ for pa in applied_parts])
    interval = int(verification_interval) if verification_interval not in [None, "Nessuno"] else None

    with DatabaseConnection() as conn:
        is_deleted_val = 0 if reactivate else conn.execute(
            "SELECT is_deleted FROM devices WHERE id=?", (dev_id,)
        ).fetchone()[0]

        query = """
            UPDATE devices SET 
                serial_number = ?, destination_id = ?, description = ?, 
                manufacturer = ?, model = ?, department = ?, 
                applied_parts_json = ?, customer_inventory = ?, 
                ams_inventory = ?, default_profile_key = ?,
                verification_interval = ?, last_modified = ?, 
                is_synced = 0, is_deleted = ?
            WHERE id = ?
        """
        params = (serial, final_destination_id, desc, mfg, model, department,
                  pa_json, customer_inv, ams_inv, default_profile_key,
                  interval, timestamp, is_deleted_val, dev_id)
        conn.execute(query, params)

def set_device_status(dev_id: int, status: str, timestamp: str):
    """Imposta lo stato di un dispositivo (active o decommissioned)."""
    if status not in ['active', 'decommissioned']:
        raise ValueError("Stato non valido.")
    with DatabaseConnection() as conn:
        conn.execute(
            "UPDATE devices SET status = ?, last_modified = ?, is_synced = 0 WHERE id = ?",
            (status, timestamp, dev_id)
        )

def wipe_all_syncable_data():
    """Cancella i dati locali per forzare un full-sync dal server."""
    with DatabaseConnection() as conn:
        for table in ["verifications","devices","destinations","profile_tests","profiles","mti_instruments","customers"]:
            conn.execute(f"DELETE FROM {table}")
        # eventuale pulizia firme locali se vuoi ripopolarle dal server:
        # conn.execute("DELETE FROM signatures")

def soft_delete_device(dev_id, timestamp):
    with DatabaseConnection() as conn:
        conn.execute("UPDATE devices SET is_deleted=1, last_modified=?, is_synced=0 WHERE id=?", (timestamp, dev_id,))
    logging.warning(f"Dispositivo ID {dev_id} marcato come eliminato.")

def soft_delete_all_devices_for_customer(customer_id, timestamp):
    with DatabaseConnection() as conn:
        cursor = conn.execute("""
            UPDATE devices
            SET is_deleted = 1, last_modified = ?, is_synced = 0
            WHERE destination_id IN (SELECT id FROM destinations WHERE customer_id = ?)
        """, (timestamp, customer_id))
    logging.warning(f"Marcati come eliminati {cursor.rowcount} dispositivi per il cliente ID {customer_id}.")
    return True

def move_device_to_destination(device_id, new_destination_id, timestamp):
    """Sposta un dispositivo aggiornando il suo destination_id."""
    with DatabaseConnection() as conn:
        conn.execute(
            "UPDATE devices SET destination_id = ?, last_modified = ?, is_synced = 0 WHERE id = ?",
            (new_destination_id, timestamp, device_id)
        )

def get_devices_for_destination(destination_id: int, search_query=None):
    """Recupera tutti i dispositivi ATTIVI per una specifica destinazione."""
    with DatabaseConnection() as conn:
        query = "SELECT * FROM devices WHERE destination_id = ? AND is_deleted = 0 AND status = 'active'"
        params = [destination_id]
        if search_query:
            query += " AND (description LIKE ? OR serial_number LIKE ? OR model LIKE ?)"
            params.extend([f"%{search_query}%"] * 3)
        query += " ORDER BY description"
        return conn.execute(query, params).fetchall()

def get_devices_for_destination_manager(destination_id: int, search_query=None):
    """Recupera TUTTI i dispositivi (attivi e dismessi) per il manager."""
    with DatabaseConnection() as conn:
        query = "SELECT * FROM devices WHERE destination_id = ? AND is_deleted = 0" # No status filter
        params = [destination_id]
        if search_query:
            query += " AND (description LIKE ? OR serial_number LIKE ? OR model LIKE ? OR AMS_inventory LIKE ? OR Customer_inventory LIKE ?)"
            params.extend([f"%{search_query}%"] * 5)
        query += " ORDER BY status, description" # Ordina per stato
        return conn.execute(query, params).fetchall()

def get_device_by_serial(serial_number: str):
    """Trova un dispositivo per numero di serie (solo non eliminati)."""
    with DatabaseConnection() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE serial_number = ? AND is_deleted = 0", 
            (serial_number,)
        ).fetchone()
        return _decode_json_fields(row, ['applied_parts_json']) if row else None

def get_all_unique_device_descriptions():
    """Recupera una lista di tutte le descrizioni uniche dei dispositivi."""
    with DatabaseConnection() as conn:
        query = "SELECT DISTINCT description FROM devices WHERE is_deleted = 0 AND description IS NOT NULL AND description <> '' ORDER BY description"
        rows = conn.execute(query).fetchall()
        # Restituisce una lista di stringhe, non di tuple
        return [row['description'] for row in rows]

def get_devices_by_description(description: str):
    """Recupera tutti i dispositivi che corrispondono a una specifica descrizione."""
    with DatabaseConnection() as conn:
        query = "SELECT id, description, serial_number, model FROM devices WHERE description = ? AND is_deleted = 0"
        return conn.execute(query, (description,)).fetchall()

def bulk_update_device_description(old_description: str, new_description: str, timestamp: str):
    """
    Aggiorna la descrizione per tutti i dispositivi che corrispondono alla vecchia descrizione.
    Restituisce il numero di righe modificate.
    """
    with DatabaseConnection() as conn:
        cursor = conn.execute(
            "UPDATE devices SET description = ?, last_modified = ?, is_synced = 0 WHERE description = ? AND is_deleted = 0",
            (new_description, timestamp, old_description)
        )
        logging.info(f"Aggiornate {cursor.rowcount} descrizioni da '{old_description}' a '{new_description}'.")
        return cursor.rowcount


def get_devices_for_customer(customer_id, search_query=None):
    with DatabaseConnection() as conn:
        query = """
            SELECT d.* FROM devices d
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE dest.customer_id = ? AND d.is_deleted = 0
        """
        params = [customer_id]
        if search_query:
            query += " AND (d.description LIKE ? OR d.serial_number LIKE ? OR d.model LIKE ?)"
            params.extend([f"%{search_query}%"]*3)
        query += " ORDER BY d.description"
        return conn.execute(query, params).fetchall()

def get_device_by_id(device_id: int):
    with DatabaseConnection() as conn:
        device_row = conn.execute("SELECT * FROM devices WHERE id = ? AND is_deleted = 0", (device_id,)).fetchone()
    return _decode_json_fields(device_row, ['applied_parts_json'])
    
def device_exists(serial_number: str):
    """Controlla se esiste un dispositivo ATTIVO con un dato seriale."""
    with DatabaseConnection() as conn:
        return conn.execute("SELECT id FROM devices WHERE serial_number = ? AND is_deleted = 0 AND status = 'active'", (serial_number,)).fetchone() is not None

def get_device_count_for_customer(customer_id):
    with DatabaseConnection() as conn:
        return conn.execute("""
            SELECT COUNT(d.id)
            FROM devices d
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE dest.customer_id = ? AND d.is_deleted = 0
        """, (customer_id,)).fetchone()[0]

def get_devices_needing_verification(days_in_future=30):
    """Recupera i dispositivi ATTIVI con verifica scaduta o in scadenza."""
    from datetime import date, timedelta
    future_date = date.today() + timedelta(days=days_in_future)
    
    with DatabaseConnection() as conn:
        query = """
            SELECT d.*, c.name as customer_name 
            FROM devices d
            JOIN destinations dest ON d.destination_id = dest.id
            JOIN customers c ON dest.customer_id = c.id
            WHERE d.next_verification_date IS NOT NULL 
            AND d.next_verification_date <= ?
            AND d.is_deleted = 0 AND d.status = 'active'
            ORDER BY d.next_verification_date ASC
        """
        return conn.execute(query, (future_date.strftime('%Y-%m-%d'),)).fetchall()
    
def search_device_globally(search_term):
    """
    Cerca un dispositivo in tutto il database e restituisce anche il nome del cliente
    a cui appartiene, navigando attraverso le destinazioni.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT d.*, c.name as customer_name 
            FROM devices d
            JOIN destinations dest ON d.destination_id = dest.id
            JOIN customers c ON dest.customer_id = c.id
            WHERE (
                d.serial_number LIKE ? OR 
                d.ams_inventory LIKE ? OR 
                d.description LIKE ? OR 
                d.model LIKE ?
            ) AND d.is_deleted = 0
        """
        like_term = f"%{search_term}%"
        rows = conn.execute(query, (like_term, like_term, like_term, like_term)).fetchall()
        
        if not rows:
            return []
        
        results = [_decode_json_fields(row, ['applied_parts_json']) for row in rows]
        return results

def get_devices_with_last_verification_for_destination(destination_id: int):
    """
    Recupera tutti i dispositivi di una destinazione con i dati della loro ultima verifica.
    Ora include l'inventario cliente e il nome della destinazione.
    """
    with DatabaseConnection() as conn:
        
        query = """
            SELECT
                CASE
                    WHEN d.status = "active" THEN "ATTIVO"
                    WHEN d.status = "inactive" THEN "DISMESSO"
                END AS "STATO",
                d.ams_inventory AS "INVENTARIO AMS",
                d.customer_inventory AS "INVENTARIO CLIENTE",
                d.description AS "DENOMINAZIONE", 
                d.manufacturer AS "MARCA",
                d.model AS "MODELLO",
                d.serial_number AS "MATRICOLA",
                d.department AS "REPARTO",
                v.verification_date AS "DATA",
                v.technician_name AS "TECNICO",
                CASE
                    WHEN v.overall_status = "PASSATO" THEN "CONFORME"
                    WHEN v.overall_status = "FALLITO" THEN "NON CONFORME"
                END AS "ESITO",
                dest.name AS "DESTINAZIONE" 
            FROM
                devices d
            LEFT JOIN
                (
                    SELECT
                        *,
                        ROW_NUMBER() OVER(PARTITION BY device_id ORDER BY verification_date DESC) as rn
                    FROM verifications
                    WHERE is_deleted = 0
                ) v ON d.id = v.device_id AND v.rn = 1
            JOIN
                destinations dest ON d.destination_id = dest.id
            WHERE
                d.destination_id = ? AND d.is_deleted = 0
            ORDER BY
                d.description;
        """
        return conn.execute(query, (destination_id,)).fetchall()

def get_devices_with_verifications_for_destination_by_date_range(destination_id: int, start_date: str, end_date: str):
    """
    Recupera TUTTI i dispositivi di una destinazione. Se sono state eseguite
    verifiche nell'intervallo di date specificato, include SOLO i dati della
    verifica PIÙ RECENTE per ciascun dispositivo.
    """
    with DatabaseConnection() as conn:
        # --- INIZIO QUERY CORRETTA ---
        # La query ora recupera TUTTI i dispositivi della destinazione.
        # Poi, tramite un LEFT JOIN su una sottoquery (RankedVerifications), associa
        # i dati della verifica PIÙ RECENTE eseguita nell'intervallo di date.
        # Se un dispositivo non ha verifiche nel periodo, i campi relativi (DATA, TECNICO, ESITO)
        # risulteranno vuoti, ma il dispositivo sarà comunque presente una sola volta.
        query = """
            WITH RankedVerifications AS (
                SELECT
                    v.*,
                    ROW_NUMBER() OVER(PARTITION BY v.device_id ORDER BY v.verification_date DESC) as rn
                FROM
                    verifications v
                WHERE
                    v.is_deleted = 0
                    AND v.verification_date BETWEEN ? AND ?
            )
            SELECT
                CASE 
                    WHEN d.status = "active" THEN "IN USO"
                    ELSE "DISMESSO" 
                END AS "STATO",
                d.ams_inventory AS "INVENTARIO AMS",
                d.customer_inventory AS "INVENTARIO CLIENTE",
                d.description AS "DENOMINAZIONE", 
                d.manufacturer AS "MARCA",
                d.model AS "MODELLO",
                d.serial_number AS "MATRICOLA",
                d.department AS "REPARTO",
                rv.verification_date AS "DATA",
                rv.technician_name AS "TECNICO",
                CASE 
                    WHEN rv.overall_status = "PASSATO" THEN "CONFORME" 
                    WHEN rv.overall_status = "FALLITO" THEN "NON CONFORME"
                END AS "ESITO",
                dest.name AS "DESTINAZIONE" 
            FROM 
                devices d
            JOIN 
                destinations dest ON d.destination_id = dest.id
            LEFT JOIN 
                RankedVerifications rv ON d.id = rv.device_id AND rv.rn = 1
            WHERE 
                d.destination_id = ? AND d.is_deleted = 0
            ORDER BY 
                d.description;
        """
        # I parametri devono corrispondere ai '?' nella query nell'ordine corretto
        return conn.execute(query, (start_date, end_date, destination_id)).fetchall()
    
def get_devices_for_customer_inventory_export(customer_id: int):
    """Get devices for customer inventory export."""
    with DatabaseConnection() as conn:
        query = """
            SELECT 
                d.ams_inventory as ams_inventory,
                d.customer_inventory as customer_inventory,
                d.description as description,
                d.manufacturer as manufacturer,
                d.model as model,
                d.serial_number as serial_number,
                dest.name as destination,
                CASE 
                    WHEN d.status = "active" THEN "ATTIVO"
                    WHEN d.status = "inactive" THEN "DISMESSO"
                END AS "status"
            FROM devices d
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE dest.customer_id = ?
            AND d.is_deleted = 0
            ORDER BY d.description
        """
        return conn.execute(query, (int(customer_id),)).fetchall()

def add_destination(uuid, customer_id, name, address, timestamp):
    """Aggiunge una nuova destinazione."""
    with DatabaseConnection() as conn:
        conn.execute(
            "INSERT INTO destinations (uuid, customer_id, name, address, last_modified, is_synced, is_deleted) VALUES (?, ?, ?, ?, ?, 0, 0)",
            (uuid, customer_id, name, address, timestamp)
        )

def update_destination(dest_id, name, address, timestamp):
    """Aggiorna una destinazione."""
    with DatabaseConnection() as conn:
        conn.execute(
            "UPDATE destinations SET name = ?, address = ?, last_modified = ?, is_synced = 0 WHERE id = ?",
            (name, address, timestamp, dest_id)
        )

def delete_destination(dest_id, timestamp):
    """Esegue un soft delete di una destinazione."""
    with DatabaseConnection() as conn:
        # Qui potresti aggiungere un controllo per impedire l'eliminazione se ci sono dispositivi
        conn.execute("UPDATE destinations SET is_deleted = 1, last_modified = ?, is_synced = 0 WHERE id = ?", (timestamp, dest_id))

def get_device_count_for_destination(destination_id: int):
    """
    Conta quanti dispositivi attivi sono presenti in una specifica destinazione.
    """
    with DatabaseConnection() as conn:
        # Esegue una query per contare le righe
        count = conn.execute(
            "SELECT COUNT(id) FROM devices WHERE destination_id = ? AND is_deleted = 0",
            (destination_id,)
        ).fetchone()[0]
    return count

def get_destinations_for_customer(customer_id: int, search_query: str = None):
    """Recupera tutte le destinazioni attive per un cliente."""
    with DatabaseConnection() as conn:
        query = "SELECT * FROM destinations WHERE customer_id = ? AND is_deleted = 0"
        params = [customer_id]
        if search_query:
            query += " AND (name LIKE ? OR address LIKE ?)"
            params.extend([f"%{search_query}%"] * 2)
        query += " ORDER BY name"
        return conn.execute(query, tuple(params)).fetchall()

def get_destination_by_id(destination_id: int):
    """
    Recupera una singola destinazione tramite il suo ID numerico.
    """
    with DatabaseConnection() as conn:
        row = conn.execute(
            "SELECT * FROM destinations WHERE id = ? AND is_deleted = 0",
            (destination_id,)
        ).fetchone()
        return row

def advanced_search(criteria: dict):
    """
    Esegue una query di ricerca dinamica nel database.
    """
    base_query = """
        SELECT
            c.name AS "Cliente",
            d.name AS "Destinazione",
            dev.description AS "Apparecchio",
            dev.serial_number AS "Matricola",
            dev.manufacturer AS "Marca",
            dev.model AS "Modello",
            v.verification_date AS "Data Verifica",
            v.technician_name AS "Tecnico",
            CASE
                WHEN v.overall_status = 'PASSATO' THEN 'CONFORME'
                WHEN v.overall_status = 'FALLITO' THEN 'NON CONFORME'
                ELSE 'NON VERIFICATO'
            END AS "Esito"
        FROM
            devices dev
        LEFT JOIN
            verifications v ON dev.id = v.device_id AND v.is_deleted = 0
        JOIN
            destinations d ON dev.destination_id = d.id
        JOIN
            customers c ON d.customer_id = c.id
        WHERE
            dev.is_deleted = 0
    """

    conditions = []
    params = []

    if criteria.get("customer_name"):
        conditions.append("c.name LIKE ?")
        params.append(f"%{criteria['customer_name']}%")
    
    if criteria.get("destination_name"):
        conditions.append("d.name LIKE ?")
        params.append(f"%{criteria['destination_name']}%")

    if criteria.get("device_description"):
        conditions.append("dev.description LIKE ?")
        params.append(f"%{criteria['device_description']}%")

    if criteria.get("serial_number"):
        conditions.append("dev.serial_number LIKE ?")
        params.append(f"%{criteria['serial_number']}%")

    if criteria.get("technician_name"):
        # Se cerco per tecnico, devo assicurarmi che il LEFT JOIN non fallisca
        # per i dispositivi mai verificati. Aggiungo una condizione che forza
        # l'esistenza di una verifica.
        conditions.append("v.id IS NOT NULL")
        # Questa condizione richiede che esista una verifica
        conditions.append("v.technician_name LIKE ?")
        params.append(f"%{criteria['technician_name']}%")

    if conditions:
        base_query += " AND " + " AND ".join(conditions)

    # --- NUOVA LOGICA PER CRITERI AGGIUNTIVI ---
    if criteria.get("manufacturer"):
        base_query += " AND dev.manufacturer LIKE ?"
        params.append(f"%{criteria['manufacturer']}%")

    if criteria.get("model"):
        base_query += " AND dev.model LIKE ?"
        params.append(f"%{criteria['model']}%")

    if criteria.get("start_date") and criteria.get("end_date"):
        base_query += " AND v.id IS NOT NULL AND v.verification_date BETWEEN ? AND ?"
        params.extend([criteria["start_date"], criteria["end_date"]])

    outcome = criteria.get("outcome")
    if outcome and outcome != "Qualsiasi":
        base_query += " AND v.id IS NOT NULL" # Assicura che una verifica esista
        if outcome == "Conforme":
            base_query += " AND v.overall_status = 'PASSATO'"
        elif outcome == "Non Conforme":
            base_query += " AND v.overall_status = 'FALLITO'"
        elif outcome == "Non Verificato":
            # Questo caso è complesso con il LEFT JOIN. La logica attuale
            # che mostra 'NON VERIFICATO' è un fallback quando v.id è NULL.
            # Per una ricerca esplicita, potremmo dover cambiare la query.
            # Per ora, lo ignoriamo se non è semplice.
            pass

    base_query += " ORDER BY c.name, d.name, dev.description;"

    with DatabaseConnection() as conn:
        return conn.execute(base_query, tuple(params)).fetchall()

def get_all_destinations_with_customer():
    """
    Recupera tutte le destinazioni attive, includendo l'ID e il nome del cliente associato.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT d.*, c.name as customer_name 
            FROM destinations d
            JOIN customers c ON d.customer_id = c.id
            WHERE d.is_deleted = 0 AND c.is_deleted = 0
            ORDER BY c.name, d.name
        """
        return conn.execute(query).fetchall()

def add_customer(uuid, name, address, phone, email, timestamp):
    with DatabaseConnection() as conn:
        conn.execute("INSERT INTO customers (uuid, name, address, phone, email, last_modified, is_synced) VALUES (?, ?, ?, ?, ?, ?, 0)", (uuid, name, address, phone, email, timestamp))

def add_or_get_customer(name: str, address: str):
    """Trova o crea un cliente e restituisce il suo ID."""
    with DatabaseConnection() as conn:
        # Cerca cliente esistente
        existing = conn.execute(
            "SELECT id FROM customers WHERE name = ? AND is_deleted = 0", 
            (name,)
        ).fetchone()
        
        if existing:
            return existing['id']
        
        # Crea nuovo cliente
        import uuid
        from datetime import datetime, timezone
        new_uuid = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)
        
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO customers (uuid, name, address, phone, email, last_modified, is_synced) VALUES (?, ?, ?, '', '', ?, 0)",
            (new_uuid, name, address, timestamp)
        )
        return cursor.lastrowid

def update_customer(cust_id, name, address, phone, email, timestamp):
    with DatabaseConnection() as conn:
        conn.execute("UPDATE customers SET name=?, address=?, phone=?, email=?, last_modified=?, is_synced=0 WHERE id=?", (name, address, phone, email, timestamp, cust_id))

def soft_delete_customer(cust_id, timestamp):
    with DatabaseConnection() as conn:
        # --- QUERY AGGIORNATA ---
        # Per contare i dispositivi, ora dobbiamo passare attraverso la tabella 'destinations'.
        # Questa query conta tutti i dispositivi le cui destinazioni appartengono al cliente che stiamo cercando di eliminare.
        query = """
            SELECT COUNT(id) FROM devices 
            WHERE is_deleted = 0 AND destination_id IN (
                SELECT id FROM destinations WHERE customer_id = ?
            )
        """
        count = conn.execute(query, (cust_id,)).fetchone()[0]
        # --- FINE MODIFICA ---

        if count > 0:
            return False, f"Impossibile eliminare: il cliente ha {count} dispositivi associati nelle sue destinazioni."
        
        # Se non ci sono dispositivi, procedi con l'eliminazione
        conn.execute("UPDATE customers SET is_deleted=1, last_modified=?, is_synced=0 WHERE id=?", (timestamp, cust_id))
    
    return True, "Cliente eliminato."


def get_all_customers(search_query=None):
    with DatabaseConnection() as conn:
        query = "SELECT * FROM customers WHERE is_deleted = 0"
        params = []
        if search_query:
            query += " AND name LIKE ?"
            params.append(f"%{search_query}%")
        query += " ORDER BY name"
        return conn.execute(query, params).fetchall()

def get_customer_by_id(customer_id):
    with DatabaseConnection() as conn:
        return conn.execute("SELECT * FROM customers WHERE id = ? AND is_deleted = 0", (customer_id,)).fetchone()
    
def get_signature_by_username(username: str):
    """
    Recupera i dati binari (BLOB) di una firma dal database locale.
    Restituisce i dati dell'immagine o None se non trovata.
    """
    if not username:
        return None
    with DatabaseConnection() as conn:
        row = conn.execute(
            "SELECT signature_data FROM signatures WHERE username = ?",
            (username,)
        ).fetchone()

    return row['signature_data'] if row and row['signature_data'] else None

# --- Gestione Verifiche (Verifications) ---

def generate_verification_code(conn, verification_date: str, technician_name: str = "", technician_username: str = "") -> str:
    """
    Genera un codice univoco per verifica: 2 iniziali-AAMMGG-4 cifre progressive.
    Il progressivo si resetta ogni giorno per ogni tecnico.
    Esempio: EM-240731-0001
    """
    def _initials_from(name: str) -> str:
        name = (name or "").strip()
        if not name and technician_username:
            return technician_username[:2].upper()
        parts = name.split()
        if len(parts) >= 2 and parts[0] and parts[1]:
            return (parts[0][0] + parts[1][0]).upper() # Mario Rossi -> MR
        if len(parts) == 1 and len(parts[0]) >= 2:
            return parts[0][:2].upper() # Mario -> MA
        return "XX"

    initials = _initials_from(technician_name)
    
    # Converte la data YYYY-MM-DD in AAMMGG
    try:
        date_obj = datetime.strptime(verification_date, '%Y-%m-%d')
        date_prefix = date_obj.strftime('%y%m%d')
    except (ValueError, TypeError):
        # Fallback nel caso la data non sia valida
        date_prefix = datetime.now().strftime('%y%m%d')

    # Il prefisso completo ora include iniziali e data
    full_prefix = f"{initials}-{date_prefix}-"

    cur = conn.execute("""
        SELECT verification_code
        FROM verifications
        WHERE verification_code LIKE ?
        ORDER BY verification_code DESC
        LIMIT 1;
    """, (full_prefix + "%",))
    row = cur.fetchone()

    if row and row[0]:
        try:
            # Estrae il numero dopo l'ultimo trattino
            last_num_str = row[0].split('-')[-1]
            last_num = int(last_num_str)
        except Exception:
            last_num = 0
        new_num = last_num + 1
    else:
        new_num = 1

    return f"{full_prefix}{new_num:04d}"


def save_verification(uuid, device_id, profile_name, results, overall_status,
                      visual_inspection_data, mti_info,
                      technician_name, technician_username,
                      timestamp, verification_date=None,
                      verification_code: str = None):
    if verification_date is None:
        verification_date = datetime.now().strftime('%Y-%m-%d')

    results_json = json.dumps(results)
    visual_json = json.dumps(visual_inspection_data)
    mti_data = mti_info if isinstance(mti_info, dict) else {}

    with DatabaseConnection() as conn:
        cursor = conn.cursor()

        # Se non passato, generiamo qui il codice
        if not verification_code:
            verification_code = generate_verification_code(conn, verification_date, technician_name, technician_username)

        sql_query = """
            INSERT INTO verifications (
                uuid, device_id, verification_date, profile_name,
                results_json, overall_status, visual_inspection_json,
                mti_instrument, mti_serial, mti_version, mti_cal_date,
                technician_name, technician_username,
                verification_code,
                last_modified, is_deleted, is_synced
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
        """

        params = (
            uuid, device_id, verification_date, profile_name,
            results_json, overall_status, visual_json,
            mti_data.get('instrument'),
            mti_data.get('serial'),
            mti_data.get('version'),
            mti_data.get('cal_date'),
            technician_name, technician_username,
            verification_code,
            timestamp
        )
        cursor.execute(sql_query, params)
        new_id = cursor.lastrowid
        return verification_code, new_id

def verification_exists(device_id: int, verification_date: str, profile_name: str) -> bool:
    """Verifica se esiste già una verifica per dispositivo/data/profilo."""
    with DatabaseConnection() as conn:
        result = conn.execute(
            "SELECT id FROM verifications WHERE device_id = ? AND verification_date = ? AND profile_name = ? AND is_deleted = 0",
            (device_id, verification_date, profile_name)
        ).fetchone()
        return result is not None

def get_verifications_for_destination_by_date_range(destination_id: int, start_date: str, end_date: str) -> list:
    """
    Recupera tutte le verifiche per una specifica destinazione eseguite in un dato intervallo di date.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT v.*, d.serial_number, d.ams_inventory
            FROM verifications v
            JOIN devices d ON v.device_id = d.id
            WHERE v.is_deleted = 0 AND d.is_deleted = 0
            AND d.destination_id = ?
            AND v.verification_date BETWEEN ? AND ?
            ORDER BY d.description, v.verification_date;
        """
        return conn.execute(query, (destination_id, start_date, end_date)).fetchall()

def get_full_verification_data_for_date(target_date: str) -> dict:
    """
    Recupera tutte le verifiche di una data specifica per l'export STM,
    usando la nuova struttura a destinazioni.
    """
    from datetime import datetime
    with DatabaseConnection() as conn:
        # --- UPDATED QUERY ---
        # We now use a double JOIN to get from the device to the customer
        query = """
            SELECT v.*, d.serial_number, d.description, d.manufacturer, d.model,
                   d.applied_parts_json, d.customer_inventory, d.ams_inventory,
                   c.name as customer_name, c.address as customer_address
            FROM verifications v
            JOIN devices d ON v.device_id = d.id
            JOIN destinations dest ON d.destination_id = dest.id
            JOIN customers c ON dest.customer_id = c.id
            WHERE v.verification_date = ? AND v.is_deleted = 0
            ORDER BY c.name, d.description
        """
        rows = conn.execute(query, (target_date,)).fetchall()

    export_structure = {"export_format_version": "1.0", "export_creation_date": datetime.now().isoformat(), "verifications_for_date": target_date, "verifications": []}
    for row_proxy in rows:
        row = dict(row_proxy)
        export_structure["verifications"].append({
            "customer": {"name": row["customer_name"], "address": row["customer_address"]},
            "device": {"serial_number": row["serial_number"], "description": row["description"], "manufacturer": row["manufacturer"], "model": row["model"], "applied_parts_json": row["applied_parts_json"], "customer_inventory": row["customer_inventory"], "ams_inventory": row["ams_inventory"]},
            "verification_details": {"verification_date": row["verification_date"], "profile_name": row["profile_name"], "results_json": row["results_json"], "overall_status": row["overall_status"], "visual_inspection_json": row["visual_inspection_json"], "technician_name": row.get("technician_name"), "mti_info": {"instrument": row["mti_instrument"], "serial": row["mti_serial"], "version": row["mti_version"], "cal_date": row["mti_cal_date"]}}
        })
    return export_structure

def soft_delete_verification(verification_id, timestamp):
    """Esegue un 'soft delete' di una singola verifica."""
    with DatabaseConnection() as conn:
        cursor = conn.execute(
            "UPDATE verifications SET is_deleted=1, last_modified=?, is_synced=0 WHERE id=?",
            (timestamp, verification_id)
        )
    if cursor.rowcount > 0:
        logging.warning(f"Verifica ID {verification_id} marcata come eliminata.")
        return True
    return False

def get_verifications_for_device(device_id: int, search_query: str = None):
    with DatabaseConnection() as conn:
        query = "SELECT * FROM verifications WHERE device_id = ? AND is_deleted = 0"
        params = [device_id]
        if search_query:
            query += " AND (verification_date LIKE ? OR technician_name LIKE ? OR verification_code LIKE ?)"
            like_term = f"%{search_query}%"
            params.extend([like_term] * 3)
        
        query += " ORDER BY verification_date DESC"
        rows = conn.execute(query, tuple(params)).fetchall()
    return [_decode_json_fields(r, ['results_json', 'visual_inspection_json']) for r in rows]

def get_verifications_for_destination_by_month(destination_id: int, year: int, month: int) -> list:
    """
    Recupera tutte le verifiche per una specifica destinazione eseguite in un dato mese e anno.
    """
    month_str = f"{month:02d}"
    year_str = str(year)
    
    with DatabaseConnection() as conn:
        query = """
            SELECT v.*, d.serial_number, d.ams_inventory
            FROM verifications v
            JOIN devices d ON v.device_id = d.id
            WHERE v.is_deleted = 0 AND d.is_deleted = 0
            AND strftime('%Y', v.verification_date) = ?
            AND strftime('%m', v.verification_date) = ?
            AND d.destination_id = ?
            ORDER BY d.description, v.verification_date;
        """
        return conn.execute(query, (year_str, month_str, destination_id)).fetchall()

def update_device_next_verification_date(device_id, interval_months, timestamp):
    from dateutil.relativedelta import relativedelta
    next_date = datetime.now() + relativedelta(months=int(interval_months))
    next_date_str = next_date.strftime('%Y-%m-%d')
    with DatabaseConnection() as conn:
        conn.execute("UPDATE devices SET next_verification_date = ?, last_modified = ?, is_synced = 0 WHERE id = ?", (next_date_str, timestamp, device_id))

def get_devices_with_last_verification():
    """
    Recupera tutti i dispositivi dal database, arricchiti con la data
    e l'esito della loro ultima verifica.
    """
    # --- CORREZIONE: Gestione di più verifiche nello stesso giorno ---
    # La sottoquery 'latest_ver' ora usa ROW_NUMBER() per identificare in modo univoco
    # la verifica più recente per ogni dispositivo, anche se ci sono più verifiche
    # eseguite nello stesso giorno. Questo previene la duplicazione dei dispositivi.
    query = """
    SELECT
        d.*,
        v.verification_date AS last_verification_date,
        v.overall_status AS last_verification_outcome
    FROM
        devices d
    LEFT JOIN verifications v ON v.id = (
        -- Sottoquery per trovare l'ID dell'ultima verifica per ogni dispositivo
        SELECT
            id
        FROM
            verifications
        WHERE device_id = d.id AND is_deleted = 0
        ORDER BY verification_date DESC, id DESC
        LIMIT 1
    )
    WHERE 
        d.is_deleted = 0
    ORDER BY
        d.id DESC;
    """
    with DatabaseConnection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_devices_verification_status_by_period(destination_id: int, start_date: str, end_date: str):
    """
    Recupera tutti i dispositivi di una specifica destinazione e controlla il loro
    stato di verifica in un dato intervallo di date.
    """
    with DatabaseConnection() as conn:
        # 1. Recupera tutti i dispositivi attivi della destinazione selezionata
        all_devices_query = "SELECT id, description, serial_number, model FROM devices WHERE destination_id = ? AND is_deleted = 0 ORDER BY description"
        all_devices = conn.execute(all_devices_query, (destination_id,)).fetchall()

        # 2. Recupera gli ID dei dispositivi di QUESTA destinazione che sono stati verificati nel periodo
        verified_devices_query = """
            SELECT DISTINCT device_id FROM verifications
            WHERE device_id IN (SELECT id FROM devices WHERE destination_id = ?)
            AND verification_date BETWEEN ? AND ?
            AND is_deleted = 0
        """
        verified_ids_cursor = conn.execute(verified_devices_query, (destination_id, start_date, end_date))
        verified_ids = {row['device_id'] for row in verified_ids_cursor}

    verified_list = []
    unverified_list = []

    for device_row in all_devices:
        device_dict = dict(device_row)
        if device_dict['id'] in verified_ids:
            verified_list.append(device_dict)
        else:
            unverified_list.append(device_dict)

    return verified_list, unverified_list

def get_all_devices_for_customer(customer_id: int, search_query=None):
    """
    Recupera TUTTI i dispositivi di un cliente, da tutte le sue destinazioni.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT d.* FROM devices d
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE dest.customer_id = ? AND d.is_deleted = 0
        """
        params = [customer_id]
        if search_query:
            query += " AND (d.description LIKE ? OR d.serial_number LIKE ? OR d.model LIKE ?)"
            params.extend([f"%{search_query}%"] * 3)
        query += " ORDER BY d.description"
        return conn.execute(query, params).fetchall()

def get_unverified_devices_for_destination_in_period(destination_id: int, start_date: str, end_date: str):
    """
    Returns a list of devices for a specific destination that have NOT had
    a verification within the specified period.
    """
    with DatabaseConnection() as conn:
        # First, find the IDs of devices in this destination that WERE verified in the period
        verified_devices_query = """
            SELECT DISTINCT device_id FROM verifications
            WHERE device_id IN (SELECT id FROM devices WHERE destination_id = ?)
            AND verification_date BETWEEN ? AND ?
            AND is_deleted = 0
        """
        verified_ids_cursor = conn.execute(verified_devices_query, (destination_id, start_date, end_date))
        verified_ids = {row['device_id'] for row in verified_ids_cursor}

        # Now, get all devices from this destination that are NOT in the verified list
        # We need to handle the case where verified_ids is empty
        if not verified_ids:
            unverified_devices_query = "SELECT * FROM devices WHERE destination_id = ? AND is_deleted = 0 ORDER BY description"
            params = (destination_id,)
        else:
            # Create a string of placeholders for the IN clause
            placeholders = ', '.join('?' for _ in verified_ids)
            unverified_devices_query = f"""
                SELECT * FROM devices
                WHERE destination_id = ?
                AND is_deleted = 0
                AND id NOT IN ({placeholders})
                ORDER BY description
            """
            params = (destination_id, *verified_ids)

        return conn.execute(unverified_devices_query, params).fetchall()

# --- Gestione Strumenti (Instruments) ---

def get_all_instruments():
    with DatabaseConnection() as conn:
        return conn.execute("SELECT * FROM mti_instruments WHERE is_deleted = 0 ORDER BY instrument_name").fetchall()

def add_instrument(uuid, name, serial, fw, cal_date, com_port, timestamp):
    with DatabaseConnection() as conn:
        conn.execute("INSERT INTO mti_instruments (uuid, instrument_name, serial_number, fw_version, calibration_date, com_port, last_modified, is_synced) VALUES (?, ?, ?, ?, ?, ?, ?, 0)", (uuid, name, serial, fw, cal_date, com_port, timestamp))

def update_instrument(inst_id, name, serial, fw, cal_date, com_port, timestamp):
    with DatabaseConnection() as conn:
        conn.execute("UPDATE mti_instruments SET instrument_name=?, serial_number=?, fw_version=?, calibration_date=?, com_port=?, last_modified=?, is_synced=0 WHERE id=?", (name, serial, fw, cal_date, com_port, timestamp, inst_id))

def soft_delete_instrument(inst_id, timestamp):
    with DatabaseConnection() as conn:
        conn.execute("UPDATE mti_instruments SET is_deleted=1, last_modified=?, is_synced=0 WHERE id=?", (timestamp, inst_id))

def set_default_instrument(inst_id, timestamp):
    with DatabaseConnection() as conn:
        conn.execute("UPDATE mti_instruments SET is_default = 0, last_modified=?, is_synced=0", (timestamp,))
        conn.execute("UPDATE mti_instruments SET is_default = 1, last_modified=?, is_synced=0 WHERE id = ?", (timestamp, inst_id))

# --- Statistiche ---
def get_stats():
    with DatabaseConnection() as conn:
        try:
            device_count = conn.execute("SELECT COUNT(id) FROM devices WHERE is_deleted = 0").fetchone()[0]
            customer_count = conn.execute("SELECT COUNT(id) FROM customers WHERE is_deleted = 0").fetchone()[0]
            last_verif_date = conn.execute("SELECT MAX(verification_date) FROM verifications WHERE is_deleted = 0").fetchone()[0]
        except (TypeError, IndexError):
            return {"devices": 0, "customers": 0, "last_verif": "N/A"}
    return {"devices": device_count, "customers": customer_count, "last_verif": last_verif_date if last_verif_date else "Nessuna"}


def force_update_timestamp(table_name, uuid, timestamp):
    """Aggiorna solo il timestamp di un record e lo marca come non sincronizzato."""
    with DatabaseConnection() as conn:
        conn.execute(f"UPDATE {table_name} SET last_modified = ?, is_synced = 0 WHERE uuid = ?", (timestamp, uuid))

def overwrite_local_record(table_name: str, record_data: dict):
    """
    Sovrascrive (o inserisce) un record locale con la versione fornita dal server.
    Questa funzione è dinamica e funziona per qualsiasi tabella.
    """
    with DatabaseConnection() as conn:
        # Rimuoviamo l'ID numerico locale, non ci serve. L'UUID è la nostra chiave.
        record_data.pop('id', None)
        
        # Assicuriamoci che il record sia marcato come sincronizzato
        record_data['is_synced'] = 1
        
        # Prepara le parti della query dinamicamente
        columns = record_data.keys()
        columns_str = ", ".join(columns)
        placeholders_str = ", ".join(["?"] * len(columns))
        
        # Prepara la parte di UPDATE in caso di conflitto sull'UUID
        # "excluded" è una parola chiave di SQLite per riferirsi ai valori che si stavano per inserire
        update_clause = ", ".join([f"{col} = excluded.{col}" for col in columns if col != 'uuid'])
        
        # Componi la query UPSERT completa
        query = f"""
            INSERT INTO {table_name} ({columns_str})
            VALUES ({placeholders_str})
            ON CONFLICT(uuid) DO UPDATE SET {update_clause};
        """
        
        # Prepara i parametri nell'ordine corretto
        params = tuple(record_data[col] for col in columns)
        
        try:
            conn.execute(query, params)
            logging.info(f"Record {record_data['uuid']} nella tabella '{table_name}' sovrascritto con la versione del server.")
        except Exception as e:
            logging.error(f"Fallimento UPSERT per record {record_data['uuid']} in '{table_name}'", exc_info=True)
            raise e
# ==============================================================================
# SEZIONE 4: GESTORE PROFILI DI VERIFICA
# ==============================================================================

def get_all_profiles_from_db():
    """
    Legge i profili e i test dal database locale e li ricostruisce
    nello stesso formato del vecchio file JSON.
    """
    profiles_dict = {}
    with DatabaseConnection() as conn:
        # 1. Recupera tutti i profili
        profiles_rows = conn.execute("SELECT * FROM profiles WHERE is_deleted = 0").fetchall()

        for profile_row in profiles_rows:
            profile_id = profile_row['id']
            profile_key = profile_row['profile_key']

            # 2. Per ogni profilo, recupera i suoi test
            tests_rows = conn.execute("SELECT * FROM profile_tests WHERE profile_id = ? AND is_deleted = 0", (profile_id,)).fetchall()

            tests_list = []
            for test_row in tests_rows:
                limits_data = json.loads(test_row['limits_json'] or '{}')
                limits_obj = {key: Limit(**data) for key, data in limits_data.items()}

                tests_list.append(Test(
                    name=test_row['name'],
                    parameter=test_row['parameter'],
                    limits=limits_obj,
                    is_applied_part_test=bool(test_row['is_applied_part_test'])
                ))

            profiles_dict[profile_key] = VerificationProfile(
                name=profile_row['name'],
                tests=tests_list
            )

    logging.info(f"Caricati {len(profiles_dict)} profili dal database locale.")
    return profiles_dict

def add_profile_with_tests(profile_key, profile_name, tests_list, timestamp):
    """Aggiunge un nuovo profilo e i suoi test in una singola transazione."""
    with DatabaseConnection() as conn:
        # Inserisci il profilo
        profile_uuid = str(uuid.uuid4())
        cursor = conn.execute(
            "INSERT INTO profiles (uuid, profile_key, name, last_modified, is_synced, is_deleted) VALUES (?, ?, ?, ?, 0, 0) RETURNING id",
            (profile_uuid, profile_key, profile_name, timestamp)
        )
        profile_id = cursor.fetchone()[0]

        # Inserisci i test associati
        if tests_list:
            tests_to_insert = []
            for test in tests_list:
                tests_to_insert.append((
                    str(uuid.uuid4()), profile_id, test.name, test.parameter,
                    json.dumps({k: v.__dict__ for k, v in test.limits.items()}),
                    test.is_applied_part_test, timestamp
                ))

            conn.executemany(
                "INSERT INTO profile_tests (uuid, profile_id, name, parameter, limits_json, is_applied_part_test, last_modified, is_synced, is_deleted) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)",
                tests_to_insert
            )
    return profile_id

def update_profile_with_tests(profile_id, profile_name, tests_list, timestamp):
    """Aggiorna un profilo e la sua lista di test."""
    with DatabaseConnection() as conn:
        # Aggiorna il nome del profilo
        conn.execute(
            "UPDATE profiles SET name = ?, last_modified = ?, is_synced = 0 WHERE id = ?",
            (profile_name, timestamp, profile_id)
        )

        # Approccio semplice: cancella i vecchi test e inserisce i nuovi
        # Questo marca i vecchi come eliminati e i nuovi come da inserire per il sync
        conn.execute(
            "UPDATE profile_tests SET is_deleted = 1, last_modified = ?, is_synced = 0 WHERE profile_id = ?",
            (timestamp, profile_id)
        )

        if tests_list:
            tests_to_insert = []
            for test in tests_list:
                tests_to_insert.append((
                    str(uuid.uuid4()), profile_id, test.name, test.parameter,
                    json.dumps({k: v.__dict__ for k, v in test.limits.items()}),
                    test.is_applied_part_test, timestamp
                ))

            conn.executemany(
                "INSERT INTO profile_tests (uuid, profile_id, name, parameter, limits_json, is_applied_part_test, last_modified, is_synced, is_deleted) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)",
                tests_to_insert
            )

def delete_profile(profile_id, timestamp):
    """Esegue un soft delete di un profilo e dei suoi test associati."""
    with DatabaseConnection() as conn:
        conn.execute("UPDATE profiles SET is_deleted = 1, last_modified = ?, is_synced = 0 WHERE id = ?", (timestamp, profile_id))
        conn.execute("UPDATE profile_tests SET is_deleted = 1, last_modified = ?, is_synced = 0 WHERE profile_id = ?", (timestamp, profile_id))


# ==============================================================================
# SEZIONE 5 FULL UPLOAD
# ==============================================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _get_pk_column(conn: sqlite3.Connection, table: str) -> str:
    """
    Ritorna il nome della colonna PK della tabella.
    Se non c'è una PK esplicita, ritorna 'rowid' (valido per tabelle normali).
    """
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    pk_cols = []
    for r in rows:
        # r: (cid, name, type, notnull, dflt_value, pk) oppure Row
        name = r["name"] if isinstance(r, sqlite3.Row) else r[1]
        is_pk = (r["pk"] if isinstance(r, sqlite3.Row) else r[5]) == 1
        if is_pk:
            pk_cols.append(name)
    if len(pk_cols) == 1:
        return pk_cols[0]
    # se PK multipla o assente, usiamo rowid (funziona finché non è WITHOUT ROWID)
    return "rowid"

def _ensure_uuid_for_table(conn: sqlite3.Connection, table: str) -> int:
    """
    Genera un uuid per tutte le righe della tabella che non lo hanno.
    Usa la PK reale (o rowid) per l'UPDATE.
    """
    # assicura che la colonna uuid esista (difensivo; altrove lo fai già)
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    colnames = { (c["name"] if isinstance(c, sqlite3.Row) else c[1]).lower() for c in cols }
    if "uuid" not in colnames:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN uuid TEXT")

    pk_col = _get_pk_column(conn, table)

    cur = conn.execute(f"SELECT {pk_col} FROM {table} WHERE uuid IS NULL OR uuid = ''")
    rows = cur.fetchall()
    count = 0
    for r in rows:
        # r può essere Row o tuple; recupera il valore della PK
        if isinstance(r, sqlite3.Row):
            pk_val = r[pk_col] if pk_col in r.keys() else r[0]
        else:
            pk_val = r[0]
        conn.execute(f"UPDATE {table} SET uuid=? WHERE {pk_col}=?", (str(uuid.uuid4()), pk_val))
        count += 1
    return count

def mark_everything_for_full_push(conn: sqlite3.Connection) -> dict:
    """
    Segna tutte le tabelle come 'da sincronizzare' (is_synced=0),
    forza last_modified = adesso, garantisce uuid presenti
    e normalizza serial_number placeholder -> NULL.
    """
    conn.row_factory = sqlite3.Row
    tables = [
        "customers",
        "destinations",
        "devices",
        "verifications",
        "profiles",
        "profile_tests",
        "mti_instruments",
        "signatures",
    ]
    res = {}
    now = _now_iso()

    with conn:  # transazione
        # garantisci colonne base (difensivo)
        def _col_exists(table, col):
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            names = [row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in rows]
            return col in names

        for t in tables:
            if not _col_exists(t, "uuid"):
                conn.execute(f"ALTER TABLE {t} ADD COLUMN uuid TEXT")
            if not _col_exists(t, "last_modified"):
                conn.execute(f"ALTER TABLE {t} ADD COLUMN last_modified TEXT")
            if not _col_exists(t, "is_synced"):
                conn.execute(f"ALTER TABLE {t} ADD COLUMN is_synced INTEGER NOT NULL DEFAULT 0")

        # uuid per tutte le tabelle (usando la PK corretta)
        created = {}
        for t in tables:
            created[t] = _ensure_uuid_for_table(conn, t)

        # normalizza seriali (devices)
        conn.execute("UPDATE devices SET serial_number=NULL WHERE serial_number IS NOT NULL AND TRIM(serial_number) = ''")
        for ph in config.PLACEHOLDER_SERIALS:
            conn.execute(
                "UPDATE devices SET serial_number=NULL WHERE serial_number IS NOT NULL AND UPPER(serial_number)=UPPER(?)",
                (ph,)
            )

        # marca tutto come non sincronizzato e bump last_modified
        for t in tables:
            cur = conn.execute(f"UPDATE {t} SET is_synced=0, last_modified=?", (now,))
            res[t] = {"rows_marked": cur.rowcount, "uuid_added": created[t]}

    logging.info(f"[full-push] Marcate come da sincronizzare: {res}")
    return res

# ==============================================================================
# ESECUZIONE INIZIALE
# ==============================================================================

# Applica le migrazioni del database all'avvio del modulo
migrate_database()