# main.py
import logging
import sys
import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
from PySide6.QtGui import QGuiApplication, QFontDatabase
from jose import jwt, JWTError
import app.auth_manager as auth_manager
from app import auth_manager
from dotenv import load_dotenv
from app.config import MODERN_STYLESHEET, load_verification_profiles
from app.ui.main_window import MainWindow
from app.logging_config import setup_logging
from app.backup_manager import create_backup
from app.ui.dialogs.login_dialog import LoginDialog
from app import config

load_dotenv()
# La SECRET_KEY qui deve essere IDENTICA a quella in real_server.py
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")

if __name__ == '__main__':
 # Configure High DPI settings BEFORE creating QApplication
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor
    )
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    
    app = QApplication(sys.argv)
    
    # Load Segoe UI font
    font_id = QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    if font_id < 0:
        logging.warning("Font Segoe UI non trovato, uso font di sistema")
     
    # Setup logging and create backup in the main thread
    setup_logging()
    logging.info("=====================================")
    logging.info("||   Avvio Safety Test Manager     ||")
    logging.info("=====================================")
    logging.info(f"BASE_DIR: {config.BASE_DIR}")
    logging.info(f"APP_DATA_DIR: {config.APP_DATA_DIR}")
    logging.info(f"DB_PATH: {config.DB_PATH}")
    logging.info(f"BACKUP_DIR: {config.BACKUP_DIR}")
    
    try:
        create_backup()
    except Exception as e:
        logging.error(f"Errore durante il backup: {e}")
        QMessageBox.warning(None, "Avviso", "Impossibile creare il backup automatico.")

    while True:
        logged_in_successfully = False
        
        # Handle session loading or login in the main thread
        if auth_manager.load_session_from_disk():
            logged_in_successfully = True
        else:
            # Create login dialog in the main thread
            login_dialog = LoginDialog()
            if login_dialog.exec() == QDialog.Accepted:
                try:
                    token = login_dialog.token_data['access_token']
                    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                    username = payload.get("sub")
                    role = payload.get("role")
                    full_name = payload.get("full_name", "N/D")
                    
                    auth_manager.set_current_user(username, role, token, full_name)
                    auth_manager.save_session_to_disk()
                    logged_in_successfully = True
                except (JWTError, KeyError) as e:
                    logging.error(f"Errore token: {e}")
                    QMessageBox.critical(None, "ERRORE CRITICO", 
                                      "IL TOKEN DI AUTENTICAZIONE NON È VALIDO.")
        
        if logged_in_successfully:
            try:
                # Load profiles in the main thread
                config.load_verification_profiles()
            except Exception as e:
                logging.error(f"Errore caricamento profili: {e}")
                QMessageBox.critical(None, "ERRORE CARICAMENTO PROFILI", 
                                   f"IMPOSSIBILE CARICARE I PROFILI:\n{str(e).upper()}")
                sys.exit(1)

            # Set stylesheet and create main window in the main thread
            app.setStyleSheet(config.MODERN_STYLESHEET)
            window = MainWindow()
            window.show()
            
            # Run event loop
            app.exec()
            
            if window.relogin_requested or window.restart_after_sync:
                logging.info("Riavvio richiesto (logout o post-sync)...")
                continue
            else:
                break
        else:
            break

    logging.info("Applicazione chiusa.")
    sys.exit(0)