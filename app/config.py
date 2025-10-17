# app/config.py
import json
from PySide6.QtWidgets import QMessageBox
from .data_models import Limit, Test, VerificationProfile
import logging
import os
import sys
import configparser

def get_base_dir():
    """Restituisce il percorso della cartella dell'eseguibile."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
def get_app_data_dir():
    """
    Restituisce il percorso della cartella dati dell'applicazione, creandola se non esiste.
    (es. C:\\Users\\TuoNome\\AppData\\Roaming\\SafetyTestManager)
    """
    # Il nome della tua azienda/applicazione per la cartella dati
    APP_NAME = "SafetyTestManager"
    
    # Trova la cartella AppData
    if sys.platform == "win32":
        app_data_path = os.path.join(os.environ['APPDATA'], APP_NAME)
    else: # Per Mac/Linux
        app_data_path = os.path.join(os.path.expanduser('~'), '.' + APP_NAME)
        
    # Crea la cartella se non esiste
    os.makedirs(app_data_path, exist_ok=True)
    return app_data_path
VERSIONE = "8.0.4"
BASE_DIR = get_base_dir() # La cartella del programma
APP_DATA_DIR = get_app_data_dir() # La cartella dei dati utente

# I file di dati ora vengono cercati/creati nella cartella AppData
DB_PATH = os.path.join(APP_DATA_DIR, "verifiche.db")
SESSION_FILE = os.path.join(APP_DATA_DIR, "session.json")
BACKUP_DIR = os.path.join(APP_DATA_DIR, "backups")
LOG_DIR = os.path.join(APP_DATA_DIR, "logs")
LOCK_FILE_DIR = os.path.join(APP_DATA_DIR, "sync.lock")
# Il file di configurazione viene ancora letto dalla cartella del programma
CONFIG_INI_PATH = os.path.join(BASE_DIR, "config.ini")
# --- FINE NUOVA DEFINIZIONE DEI PERCORSI ---


PLACEHOLDER_SERIALS = {
    "N.P.", "NP", "N/A", "NA", "NON PRESENTE", "-", 
    "SENZA SN", "NO SN", "MANCA SN", "N/D", "MANCANTE", "ND"
}

def load_server_url():
    """Legge l'URL del server da config.ini."""
    parser = configparser.ConfigParser()
    if os.path.exists(CONFIG_INI_PATH):
        parser.read(CONFIG_INI_PATH)
        return parser.get('server', 'url', fallback='http://localhost:8000')
    return 'http://localhost:8000'

SERVER_URL = load_server_url()
PROFILES = {}

# --- INIZIO AGGIUNTA PER UPDATER ---
def load_update_url():
    """Legge l'URL per il check degli aggiornamenti da config.ini."""
    parser = configparser.ConfigParser()
    if os.path.exists(CONFIG_INI_PATH):
        parser.read(CONFIG_INI_PATH)
        return parser.get('updater', 'url', fallback=None)
    return None

UPDATE_URL = load_update_url()
# --- FINE AGGIUNTA PER UPDATER ---

MODERN_STYLESHEET = """
    QDialog, QMainWindow {
        background-color: #f8fafc;
    }
    
    QTabWidget::pane {
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        background-color: white;
        padding: 0px;
    }
    
    QTabBar::tab {
        background-color: #f1f5f9;
        color: #475569;
        padding: 12px 24px;
        margin-right: 4px;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        font-weight: 600;
        font-size: 13px;
        min-width: 150px;
    }
    
    QTabBar::tab:selected {
        background-color: white;
        color: #2563eb;
        border-bottom: 3px solid #2563eb;
    }
    
    QTabBar::tab:hover:!selected {
        background-color: #e2e8f0;
    }
    
    QLabel {
        color: #1e293b;
        font-size: 14px;
        padding: 0;
        background-color: transparent;
    }

    QLabel#headerTitle {
        font-size: 26px;
        font-weight: 700;
        color: #1e293b;
    }

    QLabel#headerSubtitle {
        font-size: 13px;
        color: #64748b;
        font-weight: 200;
    }
    
    QLineEdit, QComboBox {
        border: 2px solid #e2e8f0;
        border-radius: 8px;
        padding: 10px 15px;
        background-color: white;
        font-size: 13px;
        selection-background-color: #2563eb;
        margin-bottom: 10px;
    }
    
    QLineEdit:focus, QComboBox:focus {
        border: 2px solid #2563eb;
        background-color: #f8fafc;
    }
    
    QLineEdit:hover, QComboBox:hover {
        border: 2px solid #cbd5e1;
    }
    
    QTableWidget {
        background-color: white;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        gridline-color: #f1f5f9;
        font-size: 12px;
        alternate-background-color: #f8fafc;
    }
    
    QTableWidget::item {
        padding: 10px 8px;
        border: none;
    }
    
    QTableWidget::item:selected {
        background-color: #dbeafe;
        color: #1e40af;
    }
    
    QTableWidget::item:hover {
        background-color: #f1f5f9;
    }
    
    QHeaderView::section {
        background-color: #f8fafc;
        color: #475569;
        padding: 12px 8px;
        border: none;
        border-bottom: 2px solid #e2e8f0;
        font-weight: 700;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    QHeaderView::section:hover {
        background-color: #e2e8f0;
    }
    
    QPushButton {
        background-color: #2563eb;
        color: white;
        border: none;
        border-radius: 8px;
        padding: 11px 22px;
        font-weight: 600;
        font-size: 12px;
        min-height: 40px;
    }
    
    QPushButton:hover {
        background-color: #1d4ed8;
    }
    
    QPushButton:pressed {
        background-color: #1e40af;
        padding: 12px 21px 10px 23px;
    }
    
    QPushButton:disabled {
        background-color: #cbd5e1;
        color: #94a3b8;
    }
    
    QPushButton#addButton {
        background-color: #16a34a;
    }
    
    QPushButton#addButton:hover {
        background-color: #15803d;
    }
    
    QPushButton#editButton {
        background-color: #2563eb;
    }
    
    QPushButton#editButton:hover {
        background-color: #1d4ed8;
    }
    
    QPushButton#deleteButton {
        background-color: #dc2626;
    }
    
    QPushButton#deleteButton:hover {
        background-color: #b91c1c;
    }
    
    QPushButton#secondaryButton {
        background-color: #64748b;
    }
    
    QPushButton#secondaryButton:hover {
        background-color: #475569;
    }
    
    QPushButton#warningButton {
        background-color: #ea580c;
    }
    
    QPushButton#warningButton:hover {
        background-color: #c2410c;
    }
    
    QScrollBar:vertical {
        border: none;
        background-color: #f1f5f9;
        width: 12px;
        border-radius: 6px;
        margin: 0px;
    }
    
    QScrollBar::handle:vertical {
        background-color: #cbd5e1;
        border-radius: 6px;
        min-height: 30px;
    }
    
    QScrollBar::handle:vertical:hover {
        background-color: #94a3b8;
    }
    
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    
    QScrollBar:horizontal {
        border: none;
        background-color: #f1f5f9;
        height: 12px;
        border-radius: 6px;
        margin: 0px;
    }
    
    QScrollBar::handle:horizontal {
        background-color: #cbd5e1;
        border-radius: 6px;
        min-width: 30px;
    }
    
    QScrollBar::handle:horizontal:hover {
        background-color: #94a3b8;
    }
    
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }
    
    QGroupBox {
        font-weight: bold;
        color: #0060a0;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        margin-top: 12px;
        background-color: white;
    }

    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 10px;
        left: 15px;
        background-color: #f8fafc;
    }
"""

def load_verification_profiles(file_path=None):
    import database
    global PROFILES
    PROFILES = {}
    try:
        # La logica ora chiama la nuova funzione del database
        PROFILES = database.get_all_profiles_from_db()
        if not PROFILES:
            logging.warning("Nessun profilo di verifica trovato nel database locale.")

        return True
    except Exception as e:
        # Rilancia qualsiasi eccezione del database
        logging.error("Errore critico durante il caricamento dei profili dal database.", exc_info=True)
        raise e