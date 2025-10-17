import shutil
import qtawesome as qta
from datetime import date, timedelta, datetime
import logging, pandas as pd
import json
import sys
import os   
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QComboBox, QGroupBox, QFormLayout, QMessageBox, QFileDialog, 
    QStyle, QStatusBar, QListWidget, QListWidgetItem, QLineEdit, QDialog, QMenu, QInputDialog, QCheckBox, QTableWidgetItem)
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import Qt, QSettings, QDate, QCoreApplication, QThread, QProcess, QObject, Signal
from app.data_models import AppliedPart
from app.ui.dialogs.user_manager_dialog import UserManagerDialog
from app.ui.dialogs.correction_dialog import CorrectionDialog
from app.ui.dialogs.advanced_search_dialog import AdvancedSearchDialog

# La main_window importa solo i moduli necessari per la UI e i servizi
from app import auth_manager, config, services
from app.ui.dialogs.utility_dialogs import AppliedPartsOrderDialog, GlobalSearchDialog
from app.ui.state_manager import AppState, StateManager
from app.updater import UpdateChecker
from app.ui.dialogs.update_dialog import UpdateDialog
from app.ui.dialogs.utility_dialogs import ExportCustomerSelectionDialog
from app.ui.overlay_widget import OverlayWidget
from app.ui.widgets import ControlPanelWidget, TestRunnerWidget
from app.backup_manager import restore_from_backup
from app.ui.dialogs import (DbManagerDialog, VisualInspectionDialog, DeviceDialog, 
                            InstrumentManagerDialog, InstrumentSelectionDialog)
from app.workers.sync_worker import SyncWorker
from app.ui.dialogs.conflict_dialog import ConflictResolutionDialog
from app import auth_manager
from app.ui.dialogs.signature_manager_dialog import SignatureManagerDialog
from app.hardware.fluke_esa612 import FlukeESA612
from app.ui.dialogs.profile_manager_dialog import ProfileManagerDialog
from app.config import LOG_DIR
import database
from app.workers.table_export_worker import InventoryExportWorker
from PySide6.QtCore import QThread


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Safety Test Manager - {config.VERSIONE}")
        app_icon = QIcon("logo.png") 
        self.setWindowIcon(app_icon)
        self.setWindowState(Qt.WindowMaximized)
        
        # Applica lo stile moderno
        self.setStyleSheet(config.MODERN_STYLESHEET)
        
        self.settings = QSettings("MyCompany", "SafetyTester")
        self.logo_path = self.settings.value("logo_path", "")
        self.relogin_requested = False
        self.restart_after_sync = False
        self.current_mti_info = None
        self.current_technician_name = ""
        self.test_runner_widget = None

        # --- INIZIO MODIFICA: Integrazione StateManager ---
        self.state_manager = StateManager()
        self.state_manager.state_changed.connect(self.handle_state_change)
        self.state_manager.message_changed.connect(self.handle_state_message_change)

        # Crea l'overlay come figlio della main window
        self.overlay = OverlayWidget(self)
        # --- FINE MODIFICA ---

        self.create_menu_bar()
        self.setStatusBar(QStatusBar(self))

        main_widget = QWidget()
        self.main_layout = QHBoxLayout(main_widget)
        self.setCentralWidget(main_widget)

        self.create_left_panel()
        self.create_right_panel()

        self.apply_permissions()
        self.load_all_data()

    def create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        self.logout_action = QAction(qta.icon('fa5s.sign-out-alt'), "Logout", self)
        self.logout_action.triggered.connect(self.logout)

        self.ripristina_db_action = QAction(qta.icon('fa5s.server'), "ripristina database", self)
        self.ripristina_db_action.triggered.connect(self.restore_database)

        self.export_log_action = QAction(QIcon("./icons/export_log.svg"), "Esporta File Log...", self)
        self.export_log_action.triggered.connect(self.export_log_file)

        file_menu.addAction(self.ripristina_db_action)
        file_menu.addAction(self.logout_action)
        file_menu.addAction(self.export_log_action)

        settings_menu = menubar.addMenu("Impostazioni")

        self.full_sync_action = QAction(qta.icon('fa5s.server'), "Sincronizza Tutto (Reset Locale)...", self)
        self.full_sync_action.triggered.connect(lambda: self.run_synchronization(full_sync=True))
        settings_menu.addAction(self.full_sync_action)

        self.force_push_action = QAction(qta.icon('fa5s.cloud-upload-alt'), "Forza Upload (tutti i dati)...", self)
        self.force_push_action.triggered.connect(self.confirm_and_force_push)
        settings_menu.addAction(self.force_push_action)

        settings_menu.addSeparator()

        self.set_com_port_action = QAction(qta.icon('fa5s.plug'), "Imposta Porta COM...", self)
        self.set_com_port_action.triggered.connect(self.configure_com_port)
        settings_menu.addAction(self.set_com_port_action)

        self.manage_instruments_action = QAction(qta.icon('fa5s.tools'), "Gestisci Strumenti di Misura...", self)
        self.manage_instruments_action.triggered.connect(self.open_instrument_manager)
        settings_menu.addAction(self.manage_instruments_action)
        settings_menu.addSeparator()

        self.set_logo_action = QAction(qta.icon('fa5s.image'), "Imposta Logo Azienda...", self)
        self.set_logo_action.triggered.connect(self.set_company_logo)
        settings_menu.addAction(self.set_logo_action)

        
        self.manage_users_action = QAction(qta.icon('fa5s.users-cog'), "Gestisci Utenti...", self)
        self.manage_users_action.triggered.connect(self.open_user_manager)
        settings_menu.addAction(self.manage_users_action)

        self.manage_profiles_action = QAction(qta.icon('fa5s.clipboard-list'), "Gestisci Profili...", self)
        self.manage_profiles_action.triggered.connect(self.open_profile_manager)
        settings_menu.addAction(self.manage_profiles_action)

        self.manage_signature_action = QAction(qta.icon('fa5s.file-signature'), "Gestisci Firma...", self)
        self.manage_signature_action.triggered.connect(self.open_signature_manager)
        settings_menu.addAction(self.manage_signature_action)

        options_menu = menubar.addMenu("&Opzioni")
        
        advanced_search_action = QAction(QIcon("./icons/search.svg"), "Ricerca Avanzata...", self)
        advanced_search_action.triggered.connect(self.open_advanced_search)
        options_menu.addAction(advanced_search_action)

        export_inventory_action = QAction(qta.icon('fa5s.file-excel'), "Esporta Inventario Cliente...", self)
        export_inventory_action.triggered.connect(self.export_customer_inventory)
        options_menu.addAction(export_inventory_action)

        options_menu.addSeparator()

        correction_action = QAction(qta.icon('fa5s.magic'), "Correggi Descrizioni Dispositivi...", self)
        correction_action.triggered.connect(self.open_correction_dialog)
        options_menu.addAction(correction_action)

        options_menu.addSeparator()

        update_action = QAction(qta.icon('fa5s.download'), "Controlla Aggiornamenti...", self)
        update_action.triggered.connect(self.check_for_updates)
        options_menu.addAction(update_action)
    
    def open_correction_dialog(self):
        """Apre la finestra di dialogo per la correzione delle descrizioni."""
        dialog = CorrectionDialog(self)
        dialog.exec()

    def open_advanced_search(self):
        """
        Apre la finestra di dialogo per la ricerca avanzata.
        """
        dialog = AdvancedSearchDialog(self)
        dialog.exec()
    
    def export_customer_inventory(self):
        dialog = ExportCustomerSelectionDialog(self)
        if dialog.exec():
            customer_id = dialog.get_selected_customer()
            customer = database.get_customer_by_id(customer_id)
            
            # Create worker and thread
            self.export_thread = QThread()
            self.export_worker = InventoryExportWorker(customer_id, customer['name'])
            self.export_worker.moveToThread(self.export_thread)
            
            # Connect signals - Fixed method name to match definition
            self.export_thread.started.connect(self.export_worker.run)
            self.export_worker.finished.connect(self.on_export_finished)  # Changed from handle_export_finished
            self.export_worker.error.connect(self.on_export_error)  # Make sure this matches too
            self.export_worker.get_save_path.connect(self.get_inventory_save_path)
            self.export_worker.finished.connect(self.export_thread.quit)
            self.export_worker.finished.connect(self.export_worker.deleteLater)
            self.export_thread.finished.connect(self.export_thread.deleteLater)
            
            # Start export
            self.export_thread.start()

    def get_inventory_save_path(self, suggested_name):
        """Handle save path selection for inventory export."""
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salva Inventario",
            os.path.join(os.path.expanduser("~"), "Desktop", suggested_name),
            "Excel Files (*.xlsx)"
        )
        
        if save_path:
            # Ensure .xlsx extension
            if not save_path.endswith('.xlsx'):
                save_path += '.xlsx'
                
        # Send path back to worker
        self.export_worker.save_path = save_path
        self.export_worker.save_path_received.emit(save_path)

    def on_export_finished(self, filepath):
        """Handle successful export."""
        QMessageBox.information(
            self,
            "Esportazione Completata",
            f"L'inventario è stato esportato in:\n{filepath}"
        )

    def on_export_error(self, error_msg):
        """Handle export error."""
        QMessageBox.critical(
            self,
            "Errore Esportazione",
            f"Si è verificato un errore durante l'esportazione:\n{error_msg}"
        )
    
    def export_log_file(self):
        """
        Esporta il file di log del giorno corrente in una posizione scelta dall'utente.
        """
        try:
            # --- INIZIO LOGICA DINAMICA ---
            # 1. Ottieni la data corrente in formato YYYY-MM-DD
            current_date = datetime.now().strftime("%Y-%m-%d")
            
            # 2. Costruisci il nome del file di log atteso per oggi
            log_filename = f"app_{current_date}.log"
            
            # 3. Combina la cartella dei log con il nome del file per ottenere il percorso completo
            log_file_path = os.path.join(LOG_DIR, log_filename)
            # --- FINE LOGICA DINAMICA ---

            # Controlla se il file di log di oggi esiste
            if not os.path.exists(log_file_path):
                QMessageBox.warning(self, "File non Trovato", f"Il file di log per oggi non è stato trovato.\nPercorso cercato: {log_file_path}")
                return

            # Apre la finestra di dialogo "Salva con nome"
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                "Salva File Log",
                log_filename, # Propone il nome del file di oggi come default
                "Log Files (*.log);;All Files (*)"
            )

            # Se l'utente annulla, esce
            if not save_path:
                return

            # Copia il file nella destinazione scelta
            shutil.copy(log_file_path, save_path)
            QMessageBox.information(self, "Esportazione Riuscita", f"Il file di log è stato salvato con successo in:\n{save_path}")

        except Exception as e:
            QMessageBox.critical(self, "Errore di Esportazione", f"Impossibile esportare il file di log.\nErrore: {e}")

    def check_for_updates(self):
        """Controlla la presenza di aggiornamenti e gestisce il processo."""
        if not config.UPDATE_URL:
            QMessageBox.information(self, "Aggiornamenti", "La funzione di aggiornamento non è configurata.")
            return

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            checker = UpdateChecker(config.UPDATE_URL)
            update_info = checker.check_for_updates()
            QApplication.restoreOverrideCursor()

            if update_info:
                reply = QMessageBox.question(
                    self,
                    "Aggiornamento Disponibile",
                    f"È disponibile una nuova versione: <b>{update_info['latest_version']}</b>.<br>"
                    f"Versione installata: {config.VERSIONE}.<br><br>"
                    "Vuoi scaricarla e installarla ora?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if reply == QMessageBox.Yes:
                    self.download_and_install_update(checker, update_info)
            else:
                QMessageBox.information(self, "Nessun Aggiornamento", "Il software è già aggiornato all'ultima versione.")

        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Errore Aggiornamento", str(e))

    def download_and_install_update(self, checker, update_info):
        dialog = UpdateDialog(checker, update_info, self)
        if dialog.exec() == QDialog.Accepted:
            UpdateChecker.run_updater_and_exit(dialog.updater_path)

    def create_left_panel(self):
        left_panel_widget = QWidget()
        left_layout = QVBoxLayout(left_panel_widget)
        self.control_panel = ControlPanelWidget(self)
        self.manage_button = QPushButton(qta.icon('fa5s.database'), " Gestione Anagrafiche")
        self.sync_button = QPushButton(qta.icon('fa5s.sync-alt'), " Sincronizza")
        self.manage_button.setObjectName("secondaryButton") # Corrisponde a #secondaryButton
        self.sync_button.setObjectName("editButton")      # Corrisponde a #editButton (blu)
        self.manage_button.clicked.connect(self.open_db_manager)
        self.sync_button.clicked.connect(self.run_synchronization)
        left_layout.addWidget(self.control_panel)
        left_layout.addWidget(self.manage_button)
        left_layout.addWidget(self.sync_button)
        left_layout.addStretch()
        self.main_layout.addWidget(left_panel_widget, 1)

    def create_right_panel(self):
        right_panel_widget = QWidget()
        self.right_layout = QVBoxLayout(right_panel_widget)
        self.selection_container = QWidget()
        selection_layout = QVBoxLayout(self.selection_container)
        session_group = self._create_session_group()
        search_group = self._create_search_group()
        manual_group = self._create_manual_selection_group()
        start_buttons_layout = QHBoxLayout()
        self.start_manual_button = QPushButton(qta.icon('fa5s.play'), " Avvia Verifica Manuale")
        self.start_auto_button = QPushButton(qta.icon('fa5s.robot'), " Avvia Verifica Automatica")
        
        self.start_manual_button.setObjectName("secondaryButton")
        self.start_auto_button.setObjectName("addButton") # Pulsante verde per azione principale

        self.start_manual_button.clicked.connect(lambda: self.start_verification(manual_mode=True))
        self.start_auto_button.clicked.connect(lambda: self.start_verification(manual_mode=False))
        start_buttons_layout.addStretch()
        start_buttons_layout.addWidget(self.start_manual_button)
        start_buttons_layout.addWidget(self.start_auto_button)
        selection_layout.addWidget(session_group)
        selection_layout.addWidget(search_group)
        selection_layout.addWidget(manual_group)
        selection_layout.addLayout(start_buttons_layout)
        selection_layout.addStretch()
        self.test_runner_container = QWidget()
        self.test_runner_layout = QVBoxLayout(self.test_runner_container)
        self.test_runner_container.hide()
        self.right_layout.addWidget(self.selection_container)
        self.right_layout.addWidget(self.test_runner_container)
        self.create_device_details_panel()
        self.right_layout.addWidget(self.device_details_group)

        self.main_layout.addWidget(right_panel_widget, 3)

        self.device_selector.currentIndexChanged.connect(self.on_device_selection_changed)
    
    def create_device_details_panel(self):
        from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QPushButton, QWidget, QGridLayout, QLabel, QScrollArea
        from PySide6.QtCore import Qt
        
        self.device_details_group = QGroupBox("Dettagli dispositivo", self)
        
        # Imposta altezza massima per il gruppo
        self.device_details_group.setMaximumHeight(250)
        
        box_layout = QVBoxLayout(self.device_details_group)
        
        # Crea un'area scrollabile per i dettagli
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.device_details_widget = QWidget()
        self.device_details_layout = QGridLayout(self.device_details_widget)
        
        # Imposta lo stretch delle colonne per una distribuzione uniforme
        self.device_details_layout.setColumnStretch(0, 0) # Etichetta col 1
        self.device_details_layout.setColumnStretch(1, 1) # Valore col 1
        self.device_details_layout.setColumnStretch(2, 0) # Etichetta col 2
        self.device_details_layout.setColumnStretch(3, 1) # Valore col 2
        
        # Imposta spaziatura più compatta
        self.device_details_layout.setHorizontalSpacing(20)
        self.device_details_layout.setVerticalSpacing(8)
        self.device_details_layout.setContentsMargins(15, 10, 15, 10)
        
        scroll_area.setWidget(self.device_details_widget)
        box_layout.addWidget(scroll_area)
        
        self.btn_edit_device = QPushButton("Modifica Dispositivo Selezionato")
        self.btn_edit_device.setObjectName("editButton")
        self.btn_edit_device.clicked.connect(self.on_edit_selected_device)
        box_layout.addWidget(self.btn_edit_device)
        
        self.on_device_selection_changed(self.device_selector.currentIndex())

    def _create_session_group(self):
        user_info = auth_manager.get_current_user_info()
        self.current_technician_name = user_info.get('full_name')
        group = QGroupBox("Sessione di Verifica Corrente")
        layout = QFormLayout(group)
        self.current_instrument_label = QLabel("Nessuno strumento selezionato")
        self.current_technician_label = QLabel(f"{self.current_technician_name}")
        change_session_btn = QPushButton("Imposta / Cambia Sessione...")
        change_session_btn.setObjectName("warningButton") 
        change_session_btn.clicked.connect(self.setup_session)
        layout.addRow("Strumento in Uso:", self.current_instrument_label)
        layout.addRow("Tecnico:", self.current_technician_label)
        layout.addRow(change_session_btn)
        return group

    def on_device_selection_changed(self, _idx: int):
        dev_id = self.device_selector.currentData()
        if not dev_id or dev_id == -1:
            self._clear_device_details()
            return
        self.update_device_details_view(dev_id)

    def _clear_device_details(self):
        for i in reversed(range(self.device_details_layout.count())):
            item = self.device_details_layout.itemAt(i)
            if item.widget():
                item.widget().deleteLater()
            self.device_details_layout.removeItem(item)

        # Aggiungi un widget vuoto per mantenere l'altezza quando non c'è nulla
        self.device_details_layout.addWidget(QLabel("Nessun dispositivo selezionato."), 0, 0, 1, 4)

    def update_device_details_view(self, dev_id: int):
        # Pulisce il layout prima di aggiungere nuovi elementi
        self._clear_device_details()

        row = services.database.get_device_by_id(dev_id)
        if not row:
            return

        dev = dict(row)

        dest_name = "—"
        try:
            dest_row = services.database.get_destination_by_id(dev.get("destination_id"))
            if dest_row:
                dest = dict(dest_row)
                cust_row = services.database.get_customer_by_id(dest.get("customer_id"))
                cust_name = (dict(cust_row).get("name") if cust_row else None)
                dest_name = f"{dest.get('name')} — {cust_name}" if cust_name else (dest.get('name') or "—")
        except Exception:
            pass

        prof_key = dev.get("default_profile_key")
        prof_label = prof_key or "—"
        try:
            from app import config
            prof_obj = config.PROFILES.get(prof_key)
            if prof_obj:
                prof_label = getattr(prof_obj, "name", prof_key) or prof_key
        except Exception:
            pass

        interval = dev.get("verification_interval")
        interval_label = str(interval) if interval not in (None, "") else "—"

        fields = [
            ("Descrizione", dev.get("description")),
            ("Produttore", dev.get("manufacturer")),
            ("Modello", dev.get("model")),
            ("S/N", dev.get("serial_number")),
            ("Destinazione", dest_name),
            ("Reparto", dev.get("department")),
            ("Inventario AMS", dev.get("ams_inventory")),
            ("Inventario Cliente", dev.get("customer_inventory")),
            ("Profilo Default", prof_label),
            ("Intervallo Verifica", interval_label),
        ]

        row_idx = 0
        for i in range(0, len(fields), 2):
            # Elemento a sinistra
            campo1, valore1 = fields[i]
            self.device_details_layout.addWidget(QLabel(f"<b>{campo1}:</b>"), row_idx, 0)
            self.device_details_layout.addWidget(QLabel(str(valore1 or "—")), row_idx, 1)

            # Elemento a destra (se esiste)
            if i + 1 < len(fields):
                campo2, valore2 = fields[i+1]
                self.device_details_layout.addWidget(QLabel(f"<b>{campo2}:</b>"), row_idx, 2)
                self.device_details_layout.addWidget(QLabel(str(valore2 or "—")), row_idx, 3)
            
            row_idx += 1

    def on_edit_selected_device(self):
        dev_id = self.device_selector.currentData()
        if not dev_id or dev_id == -1:
            QMessageBox.warning(self, "Attenzione", "Seleziona un dispositivo da modificare.")
            return

        try:
            from app.ui.dialogs.detail_dialogs import DeviceDialog

            row = services.database.get_device_by_id(dev_id)
            if not row:
                QMessageBox.critical(self, "Errore", "Impossibile caricare i dati del dispositivo.")
                return

            dev = dict(row)
            dest_id = dev.get("destination_id")
            dest_row = services.database.get_destination_by_id(dest_id) if dest_id else None
            customer_id = dict(dest_row).get("customer_id") if dest_row else None

            dlg = DeviceDialog(customer_id=customer_id,
                            destination_id=dest_id,
                            device_data=dev,
                            parent=self)

            if dlg.exec():
                data = dlg.get_data()
                services.update_device(
                    dev_id,
                    data["destination_id"], data["serial"], data["desc"], data["mfg"], data["model"],
                    data.get("department"), data.get("applied_parts", []), data.get("customer_inv"),
                    data.get("ams_inv"), data.get("verification_interval"), data.get("default_profile_key"),
                    reactivate=False
                )
                self.update_device_details_view(dev_id)
                QMessageBox.information(self, "Salvato", "Dispositivo aggiornato.")

        except Exception as e:
            logging.error("Errore durante la modifica del dispositivo", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Modifica non riuscita:\n{e}")

    def _create_search_group(self):
        group = QGroupBox("Ricerca Rapida")
        layout = QHBoxLayout(group)
        self.global_device_search_edit = QLineEdit()
        self.global_device_search_edit.setPlaceholderText("Cerca cliente o dispositivo...")
        self.global_device_search_edit.returnPressed.connect(self.perform_global_search)
        search_btn = QPushButton("Cerca")
        search_btn.setObjectName("editButton")
        search_btn.clicked.connect(self.perform_global_search)
        layout.addWidget(self.global_device_search_edit)
        layout.addWidget(search_btn)
        return group

    def setup_session(self):
        dialog = InstrumentSelectionDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.current_mti_info = dialog.getSelectedInstrumentData()
            user_info = auth_manager.get_current_user_info()
            self.current_technician_name = user_info.get('full_name')

            if self.current_mti_info:
                instrument_name = self.current_mti_info.get('instrument', 'N/A')
                serial_number = self.current_mti_info.get('serial', 'N/A')
                self.current_instrument_label.setText(f"<b>{instrument_name} (S/N: {serial_number})</b>")
                self.current_technician_label.setText(f"<b>{self.current_technician_name}</b>")
                logging.info(f"Sessione impostata per tecnico '{self.current_technician_name}' con strumento S/N {serial_number}.")
                self.statusBar().showMessage("Sessione di verifica impostata. Pronto per iniziare.", 5000)
            else:
                QMessageBox.warning(self, "Dati Mancanti", "Selezionare uno strumento valido.")

    def _create_manual_selection_group(self):
        group = QGroupBox("Selezione Manuale")
        layout = QFormLayout(group)
        self.destination_selector = QComboBox()
        self.destination_selector.setEditable(True)
        self.destination_selector.completer().setFilterMode(Qt.MatchContains)
        self.destination_selector.setPlaceholderText("Seleziona una destinazione...")
        self.destination_selector.lineEdit().setPlaceholderText("Seleziona una destinazione...")
    
        self.device_selector = QComboBox() 
        self.device_selector.setEditable(True)
        self.device_selector.completer().setFilterMode(Qt.MatchContains)
        self.profile_selector = QComboBox()
        self.filter_unverified_checkbox = QCheckBox("Mostra solo dispositivi da verificare (ultimi 60 giorni)")
        self.filter_unverified_checkbox.setChecked(True)
        device_layout = QHBoxLayout() 
        device_layout.addWidget(self.device_selector, 1)
        add_device_btn = QPushButton(qta.icon('fa5s.plus'), "")
        add_device_btn.setObjectName("addButton")
        add_device_btn.setToolTip("Aggiungi nuovo dispositivo alla destinazione"); 
        add_device_btn.clicked.connect(self.quick_add_device)
        device_layout.addWidget(add_device_btn)
        layout.addRow("Destinazione:", self.destination_selector)
        layout.addRow("Dispositivo:", device_layout)
        layout.addRow(self.filter_unverified_checkbox)
        layout.addRow("Profilo:", self.profile_selector)
        self.destination_selector.currentIndexChanged.connect(self.on_destination_selected)
        self.device_selector.currentIndexChanged.connect(self.on_device_selected)
        self.filter_unverified_checkbox.stateChanged.connect(self.on_destination_selected)
        return group
        
    def load_all_data(self):
        self.load_destinations()
        self.load_profiles()
        self.load_control_panel_data()

    def load_destinations(self):
        """Load destinations into the combo box."""
        self.destination_selector.blockSignals(True)
        self.destination_selector.clear()
        
        # Load actual destinations
        destinations = services.database.get_all_destinations_with_customer()
        for dest in destinations:
            self.destination_selector.addItem(f"{dest['customer_name']} / {dest['name']}", dest['id'])
        
        self.destination_selector.blockSignals(False)

    def load_profiles(self):
        self.profile_selector.clear()
        for key, profile in config.PROFILES.items():
            self.profile_selector.addItem(profile.name, key)

    def load_control_panel_data(self):
        self.control_panel.load_data()

    def on_destination_selected(self):
        self.device_selector.blockSignals(True)
        self.device_selector.clear()
        
        destination_id = self.destination_selector.currentData()
        if not destination_id or destination_id == -1:
            self.device_selector.addItem("Seleziona prima una destinazione...", -1)
            self.device_selector.blockSignals(False)
            self.on_device_selected()
            return

        devices = []
        if self.filter_unverified_checkbox.isChecked():
            end_date = date.today()
            start_date = end_date - timedelta(days=60)
            devices = services.database.get_unverified_devices_for_destination_in_period(
                destination_id, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')
            )
        else:
            devices = services.database.get_devices_for_destination(destination_id)
        for dev_row in devices:
            dev = dict(dev_row)
            display_text = f"{dev.get('description')} (S/N: {dev.get('serial_number')}) - (Inv AMS: {dev.get('ams_inventory')})"
            self.device_selector.addItem(display_text, dev.get('id'))
        if self.device_selector.count() > 0:
            self.device_selector.setCurrentIndex(0)

        self.device_selector.blockSignals(False)
        self.on_device_selected()
        self.on_device_selection_changed(self.device_selector.currentIndex())

    def on_device_selected(self):
        device_id = self.device_selector.currentData()
        self.profile_selector.blockSignals(True)
        if not device_id or device_id == -1: self.profile_selector.setCurrentIndex(0); self.profile_selector.blockSignals(False); return
        
        device_data = services.database.get_device_by_id(device_id)
        if device_data and device_data.get('default_profile_key'):
            index = self.profile_selector.findData(device_data['default_profile_key'])
            if index != -1: self.profile_selector.setCurrentIndex(index)
            else: self.profile_selector.setCurrentIndex(0)
        else: self.profile_selector.setCurrentIndex(0)
        self.profile_selector.blockSignals(False)
    
    def start_verification(self, manual_mode: bool):

        if not self.current_mti_info or not self.current_technician_name:
            QMessageBox.warning(self, "Sessione non Impostata", "Impostare strumento e tecnico prima di avviare una verifica.")
            return
            
        device_id = self.device_selector.currentData()
        if not device_id or device_id == -1 or self.destination_selector.currentIndex() <= 0:
            QMessageBox.warning(self, "Attenzione", "Selezionare una destinazione e un dispositivo validi."); return
            
        device_info_row = services.database.get_device_by_id(device_id)
        if not device_info_row:
            QMessageBox.critical(self, "Errore", "Impossibile trovare i dati del dispositivo selezionato."); return
        device_info = dict(device_info_row)

        profile_key = self.profile_selector.currentData()
        if not profile_key:
            QMessageBox.warning(self, "Attenzione", "Selezionare un profilo di verifica."); return
        
        selected_profile = config.PROFILES[profile_key]
        
        if device_info.get('default_profile_key') != profile_key:
            try:
                logging.info(f"Updating default profile for device ID {device_id} to '{profile_key}'.")
                
                update_data = {
                    "destination_id": device_info['destination_id'],
                    "default_profile_key": profile_key,
                    "serial": device_info['serial_number'],
                    "desc": device_info['description'],
                    "mfg": device_info['manufacturer'],
                    "model": device_info['model'],
                    "department": device_info['department'],
                    "customer_inv": device_info['customer_inventory'],
                    "ams_inv": device_info['ams_inventory'],
                    "applied_parts": [AppliedPart(**pa) for pa in device_info.get('applied_parts', [])],
                    "verification_interval": device_info['verification_interval']
                }
                services.update_device(device_id, **update_data)
            except Exception as e:
                logging.error(f"Failed to save default profile for device ID {device_id}: {e}")
                QMessageBox.warning(self, "Salvataggio Profilo Fallito", 
                                    "Non è stato possibile salvare il profilo scelto come predefinito, ma la verifica può continuare.")

        profile_needs_ap = any(test.is_applied_part_test for test in selected_profile.tests)
        applied_parts = [AppliedPart(**pa) for pa in device_info.get('applied_parts', [])]
        
        if not manual_mode and profile_needs_ap and applied_parts:
            order_dialog = AppliedPartsOrderDialog(applied_parts, self)
            if order_dialog.exec() != QDialog.Accepted:
                self.statusBar().showMessage("Verifica annullata dall'utente.", 3000)
                return

        if profile_needs_ap and not applied_parts:
            msg_box = QMessageBox(QMessageBox.Question, "Parti Applicate Mancanti",
                                f"Il profilo '{selected_profile.name}' richiede test su Parti Applicate, ma il dispositivo non ne ha.",
                                QMessageBox.NoButton, self)
            btn_edit = msg_box.addButton("Modifica Dispositivo", QMessageBox.ActionRole)
            msg_box.addButton("Continua (Salta Test P.A.)", QMessageBox.ActionRole)
            btn_cancel = msg_box.addButton("Annulla Verifica", QMessageBox.RejectRole)
            msg_box.exec()
            
            clicked_btn = msg_box.clickedButton()
            if clicked_btn == btn_edit:
                destination_info = dict(services.database.get_destination_by_id(device_info['destination_id']))
                customer_id = destination_info['customer_id']
                edit_dialog = DeviceDialog(customer_id=customer_id, destination_id=device_info['destination_id'], device_data=device_info, parent=self)
                if edit_dialog.exec():
                    services.update_device(device_id, **edit_dialog.get_data())
                    self.on_destination_selected()
                return
            elif clicked_btn == btn_cancel:
                return

        inspection_dialog = VisualInspectionDialog(self)
        if inspection_dialog.exec() == QDialog.Accepted:
            visual_inspection_data = inspection_dialog.get_data()
            
            if self.test_runner_widget:
                self.test_runner_widget.deleteLater()

            destination_info = dict(services.database.get_destination_by_id(device_info['destination_id']))
            customer_info = dict(services.database.get_customer_by_id(destination_info['customer_id']))
            report_settings = {"logo_path": self.logo_path}
            current_user = auth_manager.get_current_user_info()
            
            self.test_runner_widget = TestRunnerWidget(
                device_info, customer_info, self.current_mti_info, report_settings,
                profile_key, visual_inspection_data, 
                current_user.get('full_name'), 
                current_user.get('username'),
                manual_mode, self
            )
            self.test_runner_layout.addWidget(self.test_runner_widget)
            
            self.set_selection_enabled(False)
    
    def reset_main_ui(self):
        QApplication.restoreOverrideCursor()
        if self.test_runner_widget:
            self.test_runner_widget.deleteLater()
            self.test_runner_widget = None
        
        self.set_selection_enabled(True)
        self.load_control_panel_data()
        self.on_destination_selected()

    def set_selection_enabled(self, enabled):
        if enabled:
            self.selection_container.show()
            self.test_runner_container.hide()
        else:
            self.selection_container.hide()
            self.test_runner_container.show()
        self.menuBar().setEnabled(enabled)
    
    def quick_add_device(self):
        destination_id = self.destination_selector.currentData()
        if not destination_id or destination_id == -1:
            QMessageBox.warning(self, "Attenzione", "Selezionare una destinazione prima di aggiungere un dispositivo.")
            return
        
        destination_data = services.database.get_destination_by_id(destination_id)
        if not destination_data: return
        customer_id = destination_data['customer_id']

        dialog = DeviceDialog(customer_id=customer_id, destination_id=destination_id, parent=self)
        if dialog.exec():
            data = dialog.get_data()
            try:
                services.add_device(**data)
                self.on_destination_selected()
            except ValueError as e:
                QMessageBox.warning(self, "Errore", str(e))

    def confirm_and_force_push(self):
        reply = QMessageBox.question(
            self, "Conferma Forza Upload",
            ("Questa azione segna TUTTI i dati locali come da sincronizzare e li invierà al server "
            "alla prossima sincronizzazione.\n\nProcedere?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            stats = services.force_full_push()
            self.run_synchronization(full_sync=False)
            QMessageBox.information(self, "Operazione completata",
                                    "Tutti i dati sono stati marcati come da sincronizzare.\n"
                                    "Ho avviato la sincronizzazione.")
        except Exception as e:
            logging.exception("Errore durante force_full_push")
            QMessageBox.critical(self, "Errore", f"Impossibile preparare il full push:\n{e}")

    def restore_database(self):
        reply = QMessageBox.question(self, 'Conferma Ripristino Database',
                                     "<b>ATTENZIONE:</b> L'operazione è irreversibile.\n\nL'applicazione verrà chiusa al termine. Vuoi continuare?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.No: return
        backup_path, _ = QFileDialog.getOpenFileName(self, "Seleziona un file di backup", "backups", "File di Backup (*.bak)")
        if not backup_path: return
        success = restore_from_backup(backup_path)
        if success:
            QMessageBox.information(self, "Ripristino Completato", "Database ripristinato con successo. L'applicazione verrà chiusa.")
        else:
            QMessageBox.critical(self, "Errore di Ripristino", "Errore durante il ripristino. Controllare i log.")
        QApplication.quit()

    def set_company_logo(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Seleziona Logo", "", "Image Files (*.png *.jpg *.jpeg)")
        if filename:
            self.logo_path = filename
            self.settings.setValue("logo_path", filename)
            QMessageBox.information(self, "Impostazioni Salvate", f"Logo impostato su:\n{filename}")

    def open_instrument_manager(self):
        dialog = InstrumentManagerDialog(self)
        dialog.exec()

    def closeEvent(self, event):
        # --- INIZIO MODIFICA: Controllo stato prima di chiudere ---
        if not self.state_manager.is_idle():
            QMessageBox.warning(self, "Operazione in Corso", "Attendi la fine della sincronizzazione o di altre operazioni prima di chiudere.")
            event.ignore()
            return
        # --- FINE MODIFICA ---
        self.settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(event)

    def apply_permissions(self):
        user_role = auth_manager.get_current_role()
        user_info = auth_manager.get_current_user_info()
        self.setWindowTitle(f"Safety Test Manager {config.VERSIONE} - Utente: {user_info['full_name']}")
        is_technician = (user_role == 'technician')
        if hasattr(self, 'manage_profiles_action'):
            self.manage_profiles_action.setVisible(not is_technician)
        if hasattr(self, 'manage_users_action'):
            self.manage_users_action.setVisible(not is_technician)
        if hasattr (self, 'force_push_action' ):
            self.force_push_action.setVisible(not is_technician)
        if hasattr (self, 'manage_instruments_action' ):
            self.manage_instruments_action.setVisible(not is_technician)

    def update_device_list(self):
        customer_id = self.customer_selector.currentData()
        self.device_selector.clear()
        if not customer_id or customer_id == -1:
            return
        devices = []
        if self.filter_unverified_checkbox.isChecked():
            end_date = date.today()
            start_date = end_date - timedelta(days=60)
            devices = services.database.get_unverified_devices_in_period(
                customer_id, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')
            )
        else:
            devices = services.database.get_devices_for_customer(customer_id)
        for dev_row in devices:
            dev = dict(dev_row)
            display_text = f"{dev.get('description')} (S/N: {dev.get('serial_number')} - (Inv AMS: {dev.get('ams_inventory')})"
            if dev.get('ams_inventory'):
                display_text += f" / Inv. AMS: {dev.get('ams_inventory')}"
            display_text += ")"
            self.device_selector.addItem(display_text, dev.get('id'))

    def open_profile_manager(self):
        """Apre la finestra di dialogo per la gestione dei profili."""
        dialog = ProfileManagerDialog(self)
        dialog.exec()
        
        # Se i profili sono cambiati, ricarica il ComboBox nella UI principale
        if dialog.profiles_changed:
            logging.info("I profili sono stati modificati. Ricaricamento in corso...")
            # --- INIZIO CODICE CORRETTO ---
            config.load_verification_profiles() # Ricarica i profili dalla fonte dati (DB)
            self.load_profiles() # Usa la funzione corretta per popolare il combobox
            # --- FINE CODICE CORRETTO ---
            QMessageBox.information(self, "Profili Aggiornati", "La lista dei profili è stata aggiornata.")

    def open_signature_manager(self):
        dialog = SignatureManagerDialog(self)
        dialog.exec()

    def logout(self):
        reply = QMessageBox.question(self, 'Conferma Logout', 
                                     'Sei sicuro di voler effettuare il logout?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            auth_manager.logout()
            self.relogin_requested = True
            self.close()

    def open_user_manager(self):
        dialog = UserManagerDialog(self)
        dialog.exec()

    def configure_com_port(self):
        current_port = self.settings.value("global_com_port", "COM1")
        try:
            available_ports = FlukeESA612.list_available_ports()
        except:
            available_ports = ["COM1", "COM2", "COM3", "COM4"]
        port, ok = QInputDialog.getItem(
            self, "Configura Porta COM",
            "Seleziona la porta COM per lo strumento di misura:",
            available_ports,
            available_ports.index(current_port) if current_port in available_ports else 0,
            False
        )
        if ok and port:
            self.settings.setValue("global_com_port", port)
            QMessageBox.information(self, "Impostazioni Salvate", 
                                f"Porta COM impostata su: {port}\n\nQuesta verrà utilizzata per tutti gli strumenti.")
    
    def run_synchronization(self, full_sync=False):
        # --- INIZIO MODIFICA: Controllo stato prima di avviare sync ---
        if not self.state_manager.can_sync():
            QMessageBox.warning(self, "Operazione non permessa", "Impossibile avviare la sincronizzazione mentre un'altra operazione è in corso.")
            return
        # --- FINE MODIFICA ---
        if full_sync:
            reply = QMessageBox.question(self, 'Conferma Sincronizzazione Totale',
                                         "<b>ATTENZIONE:</b> Questa operazione eliminerà tutti i dati locali e li riscaricherà dal server. Le modifiche non sincronizzate andranno perse.\n\nSei sicuro di voler continuare?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return

        self.start_sync_thread(full_sync) 

    def start_sync_thread(self, full_sync=False):
        """
        Avvia il processo di sincronizzazione in un thread separato
        e gestisce correttamente tutti i possibili esiti.
        """
        self.set_ui_enabled(False)
        # 1. Imposta lo stato di "sincronizzazione in corso"
        self.state_manager.set_state(AppState.SYNCING, "Sincronizzazione in corso...")

        # 2. Prepara il worker e il thread
        self.sync_thread = QThread()
        self.sync_worker = SyncWorker(full_sync=full_sync)
        self.sync_worker.moveToThread(self.sync_thread)

        # 3. Connetti i segnali del worker agli slot di gestione
        self.sync_thread.started.connect(self.sync_worker.run)
        self.sync_worker.finished.connect(self.on_sync_success)
        self.sync_worker.error.connect(self.on_sync_error)
        self.sync_worker.conflict.connect(self.on_sync_conflict)

        # Assicura che il thread venga chiuso in ogni caso
        self.sync_worker.finished.connect(self.sync_thread.quit)
        self.sync_worker.error.connect(self.sync_thread.quit)
        self.sync_worker.conflict.connect(self.sync_thread.quit)

        # Pulisce le risorse
        self.sync_thread.finished.connect(self.sync_thread.deleteLater)
        self.sync_worker.finished.connect(self.sync_worker.deleteLater)
        self.sync_worker.error.connect(self.sync_worker.deleteLater)
        self.sync_worker.conflict.connect(self.sync_worker.deleteLater)

        # 4. Avvia il thread
        self.sync_thread.start()

    def on_sync_success(self, message):
        """Gestisce il caso di sincronizzazione completata con successo."""
        QMessageBox.information(self, "Sincronizzazione Completata", message)
        self.on_sync_finished() # Chiama la funzione di pulizia

    def on_sync_finished(self):
        """
        Funzione centralizzata per ripristinare lo stato dell'UI
        al termine della sincronizzazione, indipendentemente dall'esito.
        """
        self.state_manager.set_state(AppState.IDLE)
        self.set_ui_enabled(True)
        self.load_control_panel_data()
        logging.info("Stato di sincronizzazione ripristinato.")
        self.restart_after_sync = True
        self.close()

    def on_sync_error(self, error_message):
        """Gestisce il caso di errore durante la sincronizzazione."""
        QMessageBox.critical(self, "Errore di Sincronizzazione", error_message)
        self.set_ui_enabled(True)
        self.on_sync_finished() # Chiama la funzione di pulizia

    def on_sync_conflict(self, conflicts):
        # Mantiene lo stato SYNCING ma aggiorna il messaggio
        self.state_manager.set_state(AppState.SYNCING, f"Conflitto rilevato ({len(conflicts)} record).")
        
        QMessageBox.warning(self, "Conflitto di Sincronizzazione",
                            "Sono stati rilevati dei conflitti. Risolvili uno per uno.")
        for conflict in conflicts:
            dialog = ConflictResolutionDialog(conflict, self)
            if dialog.exec() == QDialog.Accepted:
                resolution = dialog.resolution
                if resolution == "keep_local":
                    services.resolve_conflict_keep_local(conflict['table'], conflict['uuid'])
                elif resolution == "use_server":
                    services.resolve_conflict_use_server(conflict['table'], conflict['server_version'])
            else:
                QMessageBox.information(self, "Sincronizzazione Interrotta", "La sincronizzazione verrà riprovata più tardi.")
                self.state_manager.set_state(AppState.IDLE)
                return
        QMessageBox.information(self, "Riprova Sincronizzazione", "Le risoluzioni sono state applicate. Verrà ora tentata una nuova sincronizzazione.")
        self.run_synchronization()
        self.set_ui_enabled(True)

    # --- INIZIO MODIFICA: Nuovo metodo per gestire i cambi di stato ---
    def handle_state_change(self, new_state: AppState):
        """Mostra o nasconde l'overlay in base allo stato dell'applicazione."""
        is_idle = new_state == AppState.IDLE

        if is_idle:
            self.overlay.hide()
            self.statusBar().clearMessage()
        else:
            # Per qualsiasi stato non-idle, mostra l'overlay
            self.overlay.show()
            self.overlay.raise_() # Assicura che sia sempre in primo piano

    def handle_state_message_change(self, message: str):
        """Aggiorna il testo sull'overlay o sulla status bar."""
        if not self.state_manager.is_idle():
            self.overlay.setText(message)
        elif message:
            self.statusBar().showMessage(message, 5000) # Mostra per 5 secondi se idle
    # --- FINE MODIFICA ---

    def set_ui_enabled(self, enabled):
        self.setEnabled(enabled)
        if enabled:
            self.overlay.hide()
        else:
            self.overlay.show()


    def open_db_manager(self, navigate_to=None):
        current_role = auth_manager.get_current_role()
        dialog = DbManagerDialog(role=current_role, parent=self)
        dialog.setWindowState(Qt.WindowMaximized)
        if navigate_to:
            dialog.navigate_on_load(navigate_to)
        dialog.exec()
        self.load_destinations()
        self.load_control_panel_data()
    
    def resizeEvent(self, event):
        """
        Assicura che l'overlay si ridimensioni sempre con la finestra principale.
        """
        super().resizeEvent(event)
        if hasattr(self, 'overlay'):
            self.overlay.resize(self.size())

    def perform_global_search(self):
        search_term = self.global_device_search_edit.text().strip()
        if len(search_term) < 3:
            QMessageBox.warning(self, "Ricerca", "Inserisci almeno 3 caratteri.")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            results = services.search_globally(search_term)
            QApplication.restoreOverrideCursor()

            if not results:
                QMessageBox.information(self, "Ricerca", f"Nessun risultato trovato per '{search_term}'.")
                return

            if len(results) == 1 and 'serial_number' in results[0]:
                self.select_device_from_search(results[0])
            else:
                dialog = GlobalSearchDialog(results, self)
                if dialog.exec():
                    selected = dialog.selected_item
                    if not selected:
                        return
                    if 'serial_number' in selected:
                        self.select_device_from_search(selected)
                    else:
                        self.open_db_manager(navigate_to=selected)

        except Exception as e:
            QApplication.restoreOverrideCursor()
            logging.error(f"Errore nella ricerca globale: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Si è verificato un errore durante la ricerca:\n{e}")

    def select_device_from_search(self, device_data):
        destination_id = device_data.get('destination_id')
        device_id = device_data.get('id')
        if not destination_id or not device_id:
            QMessageBox.warning(self, "Dati Incompleti", "Impossibile selezionare il dispositivo, dati mancanti.")
            return

        dest_index = self.destination_selector.findData(destination_id)
        if dest_index != -1:
            self.destination_selector.setCurrentIndex(dest_index)
            QApplication.processEvents()
            device_index = self.device_selector.findData(device_id)
            if device_index != -1:
                self.device_selector.setCurrentIndex(device_index)
            else:
                # Se il dispositivo non viene trovato, potrebbe essere a causa del filtro.
                # Disattiviamo il filtro e riproviamo.
                if self.filter_unverified_checkbox.isChecked():
                    logging.info("Dispositivo non trovato con filtro attivo, disattivazione filtro e nuovo tentativo...")
                    self.filter_unverified_checkbox.setChecked(False)
                    QApplication.processEvents() # Diamo tempo alla UI di aggiornare la lista
                    device_index = self.device_selector.findData(device_id)
                    if device_index != -1:
                        self.device_selector.setCurrentIndex(device_index)

    def setup_verification_session(self):
        dialog = InstrumentSelectionDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.current_mti_info = dialog.getSelectedInstrumentData()
            user_info = auth_manager.get_current_user_info()
            self.current_technician_name = user_info.get('full_name')

            if self.current_mti_info:
                self.current_instrument_label.setText(f"<b>{self.current_mti_info.get('instrument')} (S/N: {self.current_mti_info.get('serial')})</b>")
                self.current_technician_label.setText(f"<b>{self.current_technician_name}</b>")
                logging.info(f"Sessione impostata per tecnico '{self.current_technician_name}'.")
                self.statusBar().showMessage("Sessione impostata. Pronto per avviare le verifiche.", 5000)
            else:
                QMessageBox.warning(self, "Dati Mancanti", "Selezionare uno strumento valido.")