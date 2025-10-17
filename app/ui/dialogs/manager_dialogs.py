# app/ui/dialogs/manager_dialogs.py

import logging
import pandas as pd
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QLineEdit, QLabel, QPushButton,
    QHeaderView, QAbstractItemView, QStyle, QMessageBox, QFileDialog, QProgressDialog, QFrame
)
from PySide6.QtCore import Qt, QThread, QSize
from PySide6.QtGui import QColor, QBrush, QFont, QIcon
import re
import os

from app import services, auth_manager, config  # Import config
from .detail_dialogs import CustomerDialog, DeviceDialog, InstrumentDetailDialog
from .utility_dialogs import (DateRangeSelectionDialog, VerificationStatusDialog, MonthYearSelectionDialog,
                              MappingDialog, ImportReportDialog, VerificationViewerDialog,
                              DateSelectionDialog, DestinationDetailDialog, DestinationSelectionDialog, SingleCalendarRangeDialog)
from app.workers.import_worker import ImportWorker
from app.workers.stm_import_worker import StmImportWorker
from app.workers.export_worker import DailyExportWorker
from app.workers.bulk_report_worker import BulkReportWorker
from app.workers.table_export_worker import TableExportWorker
import database


class NumericTableWidgetItem(QTableWidgetItem):
    """Un QTableWidgetItem personalizzato che si ordina numericamente."""
    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except (ValueError, TypeError):
            return super().__lt__(other)


class DbManagerDialog(QDialog):
    def __init__(self, role, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.user_role = role
        self.setWindowTitle("GESTIONE ANAGRAFICHE")
        self.resize(1400, 850)
        self._navigate_on_load_item = None
        
        # Applica gli stili moderni da config
        self.setStyleSheet(config.MODERN_STYLESHEET)
        
        self.setup_ui()
        self.load_customers_table()

    def navigate_on_load(self, item_data):
        self._navigate_on_load_item = item_data

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Header con titolo e informazioni
        header = self.create_header()
        main_layout.addWidget(header)

        # Barra delle azioni principali
        top_actions_layout = self.create_top_actions()
        main_layout.addLayout(top_actions_layout)

        # Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        main_layout.addWidget(self.tabs)

        self.setup_customer_tab()
        self.setup_destination_tab()
        self.setup_device_tab()
        self.setup_verification_tab()

        # Connessioni dei segnali
        self.customer_table.itemSelectionChanged.connect(self.customer_selected)
        self.destination_table.itemSelectionChanged.connect(self.destination_selected)
        self.device_table.itemSelectionChanged.connect(self.device_selected)
        self.customer_table.itemDoubleClicked.connect(self.navigate_to_destinations_tab)
        self.destination_table.itemDoubleClicked.connect(self.navigate_to_devices_tab)
        self.device_table.itemDoubleClicked.connect(self.navigate_to_verifications_tab)
        self.customer_search_box.textChanged.connect(self.load_customers_table)
        self.destination_search_box.textChanged.connect(self.customer_selected)
        self.device_search_box.textChanged.connect(self.destination_selected)
        self.verification_search_box.textChanged.connect(self.device_selected)
        
        self.reset_views(level='customer')

    def create_header(self):
        """Crea un header moderno per la finestra"""
        header_widget = QFrame()
        header_widget.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 10px;
                padding: 8px;
                border: 1px solid #e2e8f0;
            }
        """)
        
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(15, 10, 15, 10)
        
        # Titolo principale
        title_layout = QVBoxLayout()
        title = QLabel("📋 GESTIONE ANAGRAFICHE")
        title.setObjectName("headerTitle")
        title.setStyleSheet("border: none;")

        
        subtitle = QLabel("Sistema di gestione clienti, destinazioni e dispositivi")
        subtitle.setObjectName("headerSubtitle")
        subtitle.setStyleSheet("border: none; margin-top: 3px;")
        
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)
        
        
        # Info utente
        ruolo = "AMMINISTRATORE" if self.user_role == "admin" else "TECNICO"
        user_info = QLabel(f"👤 {ruolo.upper()}")
        user_info.setStyleSheet("""
            font-size: 13px;
            color: #475569;
            font-weight: 200;
            background-color: #f1f5f9;
            padding: 6px 8px;
            border-radius: 20px;
        """)
        
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        header_layout.addWidget(user_info)
        
        return header_widget

    # --- Setup delle Schede (Tabs) ---
    def setup_customer_tab(self):
        self.customer_tab = QWidget()
        self.tabs.addTab(self.customer_tab, "👥 CLIENTI")
        layout = QVBoxLayout(self.customer_tab)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)
        
        self.customer_search_box = QLineEdit()
        self.customer_search_box.setPlaceholderText("🔍 Cerca cliente per nome, indirizzo, telefono o email...")
        
        self.customer_table = QTableWidget(0, 5)
        self.customer_table.setHorizontalHeaderLabels(["ID", "NOME", "INDIRIZZO", "TELEFONO", "EMAIL"])
        self.setup_table_style(self.customer_table)
        
        buttons_layout = self.create_customer_buttons()
        
        layout.addWidget(self.customer_search_box)
        layout.addWidget(self.customer_table)
        layout.addLayout(buttons_layout)

    def setup_destination_tab(self):
        self.destination_tab = QWidget()
        self.tabs.addTab(self.destination_tab, "📍 DESTINAZIONI")
        layout = QVBoxLayout(self.destination_tab)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)
        
        self.destination_label = QLabel("ℹ️ Seleziona un cliente dalla scheda precedente")
        self.destination_label.setStyleSheet("background-color: #f1f5f9; border-radius: 6px; padding: 8px; margin-bottom: 8px; font-weight: 600;")

        self.destination_search_box = QLineEdit()
        self.destination_search_box.setPlaceholderText("🔍 Cerca destinazione per nome o indirizzo...")
        
        self.destination_table = QTableWidget(0, 3)
        self.destination_table.setHorizontalHeaderLabels(["ID", "NOME", "INDIRIZZO"])
        self.setup_table_style(self.destination_table)
        
        buttons_layout = self.create_destination_buttons()
        
        layout.addWidget(self.destination_label)
        layout.addWidget(self.destination_search_box)
        layout.addWidget(self.destination_table)
        layout.addLayout(buttons_layout)
        
    def setup_device_tab(self):
        self.device_tab = QWidget()
        self.tabs.addTab(self.device_tab, "⚙️ DISPOSITIVI")
        layout = QVBoxLayout(self.device_tab)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)
        
        self.device_label = QLabel("ℹ️ Seleziona una destinazione dalla scheda precedente")
        self.device_label.setStyleSheet("background-color: #f1f5f9; border-radius: 6px; padding: 8px; margin-bottom: 8px; font-weight: 600;")
        
        self.device_search_box = QLineEdit()
        self.device_search_box.setPlaceholderText("🔍 Cerca dispositivo per descrizione, S/N, costruttore, modello...")
        
        self.device_table = QTableWidget(0, 11)
        self.device_table.setHorizontalHeaderLabels([
            "ID", "DESCRIZIONE", "REPARTO", "S/N", "COSTRUTTORE",
            "MODELLO", "INV. CLIENTE", "INV. AMS", "INT. VERIFICA", "STATO", "ULTIMA VERIFICA"
        ])
        self.setup_table_style(self.device_table)
        
        buttons_layout = self.create_device_buttons()
        
        layout.addWidget(self.device_label)
        layout.addWidget(self.device_search_box)
        layout.addWidget(self.device_table)
        layout.addLayout(buttons_layout)

    def setup_verification_tab(self):
        self.verification_tab = QWidget()
        self.tabs.addTab(self.verification_tab, "📊 VERIFICHE")
        layout = QVBoxLayout(self.verification_tab)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)
        
        self.verification_label = QLabel("ℹ️ Seleziona un dispositivo dalla scheda precedente")
        self.verification_label.setStyleSheet("background-color: #f1f5f9; border-radius: 6px; padding: 8px; margin-bottom: 8px; font-weight: 600;")

        self.verification_search_box = QLineEdit()
        self.verification_search_box.setPlaceholderText("🔍 Cerca per data, tecnico, codice verifica...")
        
        self.verifications_table = QTableWidget(0, 6)
        self.verifications_table.setHorizontalHeaderLabels([
            "ID", "DATA", "ESITO", "PROFILO", "TECNICO", "CODICE VERIFICA"
        ])
        self.setup_table_style(self.verifications_table, hide_id=False)
        
        buttons_layout = self.create_verification_buttons()
        
        layout.addWidget(self.verification_label)
        layout.addWidget(self.verification_search_box)
        layout.addWidget(self.verifications_table)
        layout.addLayout(buttons_layout)

    # --- Metodi per la Navigazione con Doppio Click ---
    def navigate_to_destinations_tab(self):
        if self.get_selected_id(self.customer_table) is not None:
            self.tabs.setCurrentWidget(self.destination_tab)

    def navigate_to_devices_tab(self):
        if self.get_selected_id(self.destination_table) is not None:
            self.tabs.setCurrentWidget(self.device_tab)

    def navigate_to_verifications_tab(self):
        if self.get_selected_id(self.device_table) is not None:
            self.tabs.setCurrentWidget(self.verification_tab)

    # --- METODI HELPER E CREAZIONE BOTTONI ---
    def setup_table_style(self, table, hide_id=True, stretch_last=True):
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        if hide_id:
            table.hideColumn(0)

    def create_button(self, text, slot, button_type="primary", icon=None, enabled=True):
        btn = QPushButton(text.upper())
        btn.setObjectName(f"{button_type}Button")
        btn.setCursor(Qt.PointingHandCursor)
        
        if icon:
            btn.setIcon(QApplication.style().standardIcon(icon))
            btn.setIconSize(QSize(16, 16))
        
        btn.clicked.connect(slot)
        btn.setEnabled(enabled)
        return btn

    def create_top_actions(self):
        layout = QHBoxLayout()
        layout.setSpacing(12)
        
        layout.addWidget(self.create_button("⬆️ Importa Dispositivi", self.import_from_file, "addButton"))
        layout.addWidget(self.create_button("📥 Importa Archivio", self.import_from_stm, "addButton"))
        layout.addWidget(self.create_button("💾 Esporta Verifiche", self.export_daily_verifications, "secondaryButton"))
        
        layout.addStretch()
        
        layout.addWidget(self.create_button("📄 Genera Report", self.generate_monthly_reports, "editButton"))
        layout.addWidget(self.create_button("🔍 Filtra Periodo", self.open_period_filter_dialog, "secondaryButton"))
        
        return layout

    def create_customer_buttons(self):
        layout = QHBoxLayout()
        layout.setSpacing(10)
        
        self.add_cust_btn = self.create_button("➕ Aggiungi", self.add_customer, "addButton")
        self.add_cust_btn.setObjectName("addButton")
        self.edit_cust_btn = self.create_button("✏️ Modifica", self.edit_customer, "editButton", enabled=False)
        self.edit_cust_btn.setObjectName("editButton")
        self.del_cust_btn = self.create_button("🗑️ Elimina", self.delete_customer, "deleteButton", enabled=False)
        self.del_cust_btn.setObjectName("deleteButton")
        self.show_all_devices_btn = self.create_button("📋 Tutti Dispositivi", self.show_all_customer_devices, "secondaryButton", enabled=False)
        
        layout.addWidget(self.add_cust_btn)
        layout.addWidget(self.edit_cust_btn)
        layout.addWidget(self.del_cust_btn)
        layout.addWidget(self.show_all_devices_btn)
        
        if self.user_role == 'technician':
            self.del_cust_btn.setVisible(False)
            
        return layout

    def create_destination_buttons(self):
        layout = QHBoxLayout()
        layout.setSpacing(10)
        
        self.add_dest_btn = self.create_button("➕ Aggiungi", self.add_destination, "addButton", enabled=False)
        self.add_dest_btn.setObjectName("addButton")
        self.edit_dest_btn = self.create_button("✏️ Modifica", self.edit_destination, "editButton", enabled=False)
        self.edit_dest_btn.setObjectName("editButton")
        self.del_dest_btn = self.create_button("🗑️ Elimina", self.delete_destination, "deleteButton", enabled=False)
        self.del_dest_btn.setObjectName("deleteButton")
        self.export_dest_table_btn = self.create_button("📊 Excel", self.export_destination_table, "secondaryButton", enabled=False)
        
        layout.addWidget(self.add_dest_btn)
        layout.addWidget(self.edit_dest_btn)
        layout.addWidget(self.del_dest_btn)
        layout.addWidget(self.export_dest_table_btn)
       
        if self.user_role == 'technician':
            self.del_dest_btn.setVisible(False)
        return layout

    def create_device_buttons(self):
        layout = QHBoxLayout()
        layout.setSpacing(10)
        
        self.add_dev_btn = self.create_button("➕ Aggiungi", self.add_device, "addButton", enabled=False)
        self.add_dev_btn.setObjectName("addButton")
        self.edit_dev_btn = self.create_button("✏️ Modifica", self.edit_device, "editButton", enabled=False)
        self.edit_dev_btn.setObjectName("editButton")
        self.move_dev_btn = self.create_button("↔️ Sposta", self.move_device, "secondaryButton", enabled=False)
        self.decommission_dev_btn = self.create_button("❌ Dismetti", self.decommission_device, "warningButton", enabled=False)
        self.decommission_dev_btn.setObjectName("warningButton")
        self.decommission_dev_btn.setVisible(False)
        self.reactivate_dev_btn = self.create_button("✅ Riattiva", self.reactivate_device, "addButton", enabled=False)
        self.reactivate_dev_btn.setObjectName("addButton")
        self.reactivate_dev_btn.setVisible(False)
        self.del_dev_btn = self.create_button("🗑️ Elimina", self.delete_device, "deleteButton", enabled=False)
        self.del_dev_btn.setObjectName("deleteButton")

        layout.addWidget(self.add_dev_btn)
        layout.addWidget(self.edit_dev_btn)
        layout.addWidget(self.move_dev_btn)
        layout.addWidget(self.decommission_dev_btn)
        layout.addWidget(self.reactivate_dev_btn)
        layout.addWidget(self.del_dev_btn)
        
        return layout
        
    def create_verification_buttons(self):
        layout = QHBoxLayout()
        layout.setSpacing(10)
        
        self.view_verif_btn = self.create_button("👁️ Visualizza", self.view_verification_details, "editButton", enabled=False)
        self.view_verif_btn.setObjectName("editButton")
        self.gen_report_btn = self.create_button("📄 PDF", self.generate_old_report, "addButton", enabled=False)
        self.gen_report_btn.setObjectName("addButton")
        self.print_report_btn = self.create_button("🖨️ Stampa", self.print_old_report, "secondaryButton", enabled=False)
        self.print_report_btn.setObjectName("secondaryButton")
        self.delete_verif_btn = self.create_button("🗑️ Elimina", self.delete_verification, "deleteButton", enabled=False)
        self.delete_verif_btn.setObjectName("deleteButton")
        
        layout.addWidget(self.view_verif_btn)
        layout.addWidget(self.gen_report_btn)
        layout.addWidget(self.print_report_btn)
        layout.addWidget(self.delete_verif_btn)
        
        return layout
    # --- LOGICA DI GESTIONE DATI ---
    def get_selected_id(self, table: QTableWidget):
        selected_rows = table.selectionModel().selectedRows()
        if not selected_rows: return None
        id_item = table.item(selected_rows[0].row(), 0)
        return int(id_item.text()) if id_item else None

    def reset_views(self, level='customer'):
        if level == 'customer':
            self.destination_table.setRowCount(0)
            self.destination_label.setText("ℹ️ Seleziona un cliente dalla scheda precedente")
            self.set_destination_buttons_enabled(False, False)
        if level in ['customer', 'destination']:
            self.device_table.setRowCount(0)
            self.device_label.setText("ℹ️ Seleziona una destinazione dalla scheda precedente")
            self.set_device_buttons_enabled(False)
        if level in ['customer', 'destination', 'device']:
            self.verifications_table.setRowCount(0)
            self.verification_label.setText("ℹ️ Seleziona un dispositivo dalla scheda precedente")
            self.set_verification_buttons_enabled(False)


    def set_customer_buttons_enabled(self, enabled):
        self.edit_cust_btn.setEnabled(enabled)
        self.del_cust_btn.setEnabled(enabled)

    def set_destination_buttons_enabled(self, add_enabled, other_enabled):
        self.add_dest_btn.setEnabled(add_enabled)
        self.edit_dest_btn.setEnabled(other_enabled)
        self.del_dest_btn.setEnabled(other_enabled)
        self.export_dest_table_btn.setEnabled(other_enabled)

    def set_device_buttons_enabled(self, enabled):
        self.add_dev_btn.setEnabled(enabled)
        self.edit_dev_btn.setEnabled(enabled)
        self.move_dev_btn.setEnabled(enabled)
        self.del_dev_btn.setEnabled(enabled)

    def set_verification_buttons_enabled(self, enabled):
        self.view_verif_btn.setEnabled(enabled)
        self.gen_report_btn.setEnabled(enabled)
        self.print_report_btn.setEnabled(enabled)
        self.delete_verif_btn.setEnabled(enabled)

    def load_customers_table(self):
        self.reset_views(level='customer') 
        self.customer_table.setRowCount(0)
        self.customer_table.setSortingEnabled(False) 
        customers = services.get_all_customers(self.customer_search_box.text())
        
        for cust in customers:
            row = self.customer_table.rowCount()
            self.customer_table.insertRow(row)
            customer_dict = dict(cust)
            
            self.customer_table.setItem(row, 0, NumericTableWidgetItem(str(customer_dict['id'])))
            self.customer_table.setItem(row, 1, QTableWidgetItem(customer_dict['name'].upper()))
            self.customer_table.setItem(row, 2, QTableWidgetItem(customer_dict['address'].upper()))
            self.customer_table.setItem(row, 3, QTableWidgetItem(customer_dict.get('phone', '').upper()))
            self.customer_table.setItem(row, 4, QTableWidgetItem(customer_dict.get('email', '').upper()))
        
        self.customer_table.setSortingEnabled(True)
        self.customer_table.resizeRowsToContents()
        
        if self._navigate_on_load_item:
            item = self._navigate_on_load_item
            if 'address' in item:
                self.find_and_select_item(self.customer_table, item['id'])
            self._navigate_on_load_item = None

    def customer_selected(self):
        self.reset_views(level='destination')
        cust_id = self.get_selected_id(self.customer_table)
        self.set_customer_buttons_enabled(cust_id is not None)
        self.show_all_devices_btn.setEnabled(cust_id is not None)
        if cust_id:
            customer_name = self.customer_table.item(self.customer_table.currentRow(), 1).text()
            self.destination_label.setText(f"DESTINAZIONI '{customer_name.upper()}'")
            self.load_destinations_table(cust_id)
            self.set_destination_buttons_enabled(True, False)
    
    def load_destinations_table(self, customer_id):
        self.destination_table.setRowCount(0)
        self.destination_table.setSortingEnabled(False)
        search_query = self.destination_search_box.text()
        destinations = services.database.get_destinations_for_customer(customer_id, search_query)
        for dest in destinations:
            row = self.destination_table.rowCount()
            self.destination_table.insertRow(row)
            self.destination_table.setItem(row, 0, NumericTableWidgetItem(str(dest['id'])))
            self.destination_table.setItem(row, 1, QTableWidgetItem(dest['name'].upper()))
            self.destination_table.setItem(row, 2, QTableWidgetItem(dest['address'].upper()))
        self.destination_table.setSortingEnabled(True)
        self.destination_table.resizeRowsToContents()

    def destination_selected(self):
        self.reset_views(level='device')
        dest_id = self.get_selected_id(self.destination_table)
        is_dest_selected = dest_id is not None
        self.set_destination_buttons_enabled(self.get_selected_id(self.customer_table) is not None, is_dest_selected)
        if dest_id:
            dest_name = self.destination_table.item(self.destination_table.currentRow(), 1).text()
            self.device_label.setText(f"DISPOSITIVI '{dest_name.upper()}'")
            self.load_devices_table(dest_id)
            self.set_device_buttons_enabled(True)
            if self._navigate_on_load_item:
                item = self._navigate_on_load_item
                if 'serial_number' in item:
                    self.find_and_select_item(self.device_table, item['id'])
                self._navigate_on_load_item = None

    def load_devices_table(self, destination_id):
        self.device_table.setSortingEnabled(False)
        self.device_table.setRowCount(0)
        search_text = self.device_search_box.text()

        # --- INIZIO BLOCCO MODIFICATO ---
        
        # 1. Recupera i dati arricchiti dalla nuova funzione del database
        all_devices = database.get_devices_with_last_verification()
        
        # 2. Filtra i dispositivi per la destinazione corrente e la ricerca
        devices_to_show = [
            dev for dev in all_devices 
            if dev.get('destination_id') == destination_id and (
                not search_text or 
                any(search_text.lower() in str(dev.get(field, '') or '').lower() for field in 
                    ['description', 'serial_number', 'model', 'manufacturer', 'department', 'ams_inventory', 'customer_inventory'])
            )
        ]

        # Colori per le righe in base all'esito
        color_pass = QColor("#0b5f1e")  # Verde chiaro
        color_fail = QColor("#fc0217")  # Rosso chiaro
        
        for dev in devices_to_show:
            row = self.device_table.rowCount()
            self.device_table.insertRow(row)
            
            status = dev.get('status', 'active')
            status_text = 'ATTIVO' if status == 'active' else 'DISMESSO'
            
            # Popola le celle come prima
            self.device_table.setItem(row, 0, NumericTableWidgetItem(str(dev.get('id'))))
            self.device_table.setItem(row, 1, QTableWidgetItem(str(dev.get('description')).upper()))
            self.device_table.setItem(row, 2, QTableWidgetItem(str(dev.get('department')).upper()))
            self.device_table.setItem(row, 3, QTableWidgetItem(str(dev.get('serial_number')).upper()))
            self.device_table.setItem(row, 4, QTableWidgetItem(str(dev.get('manufacturer')).upper()))
            self.device_table.setItem(row, 5, QTableWidgetItem(str(dev.get('model')).upper()))
            self.device_table.setItem(row, 6, QTableWidgetItem(str(dev.get('customer_inventory')).upper()))
            self.device_table.setItem(row, 7, QTableWidgetItem(str(dev.get('ams_inventory')).upper()))
            interval = dev.get('verification_interval')
            interval_text = str(interval).upper() if interval is not None else "N/A"
            self.device_table.setItem(row, 8, NumericTableWidgetItem(interval_text))
            self.device_table.setItem(row, 9, QTableWidgetItem(status_text.upper()))
            
            # 3. Popola la nuova colonna "ULTIMA VERIFICA"
            last_ver_date = dev.get('last_verification_date', '') or "N/A"
            self.device_table.setItem(row, 10, QTableWidgetItem(str(last_ver_date).upper()))

            # 4. Applica la colorazione alla riga
            target_color = None
            last_outcome_raw = dev.get('last_verification_outcome')

            if last_outcome_raw:
                # Pulisce la stringa da spazi e la converte in maiuscolo per un confronto sicuro
                last_outcome = last_outcome_raw.strip().upper()
                
                # Controlla diverse possibili diciture per l'esito
                if last_outcome in ("PASSATO", "CONFORME"):
                    target_color = color_pass
                elif last_outcome in ("FALLITO", "NON CONFORME"):
                    target_color = color_fail
            
            # Applica il colore a tutte le celle della riga
            if target_color:
                for col_index in range(self.device_table.columnCount()):
                    # Se una cella fosse vuota, crea un item per poterla colorare
                    if not self.device_table.item(row, col_index):
                         self.device_table.setItem(row, col_index, QTableWidgetItem())
                    self.device_table.item(row, col_index).setForeground(target_color)

            # Colora il testo di blu per i dispositivi dismessi (sovrascrive lo sfondo)
            if status == 'decommissioned':
                for col in range(self.device_table.columnCount()):
                    if not self.device_table.item(row, col):
                         self.device_table.setItem(row, col, QTableWidgetItem())
                    self.device_table.item(row, col).setForeground(QBrush(QColor("blue")))

        # --- FINE BLOCCO MODIFICATO ---

        self.device_table.setSortingEnabled(True)
        self.device_table.resizeRowsToContents()

    def decommission_device(self):
        dev_id = self.get_selected_id(self.device_table)
        dest_id = self.get_selected_id(self.destination_table)
        if not dev_id or not dest_id:
            return
        reply = QMessageBox.question(self, 'CONFERMA DISMISSIONE', 
                                     "SEI SICURO DI VOLER MARCARE QUESTO DISPOSITIVO COME DISMESSO?\nNON APPARIRÀ PIÙ NELLE LISTE PER NUOVE VERIFICHE.",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            services.decommission_device(dev_id)
            self.load_devices_table(dest_id)

    def reactivate_device(self):
        dev_id = self.get_selected_id(self.device_table)
        dest_id = self.get_selected_id(self.destination_table)
        if not dev_id or not dest_id:
            return
        reply = QMessageBox.question(self, 'CONFERMA RIATTIVAZIONE', 
                                     "SEI SICURO DI VOLER RIATTIVARE QUESTO DISPOSITIVO?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            services.reactivate_device(dev_id)
            self.load_devices_table(dest_id)

    def device_selected(self):
        self.reset_views(level='verification')
        dev_id = self.get_selected_id(self.device_table)
        self.edit_dev_btn.setEnabled(False)
        self.del_dev_btn.setEnabled(False)
        self.move_dev_btn.setEnabled(False)
        self.decommission_dev_btn.setEnabled(False)
        self.reactivate_dev_btn.setVisible(False)
        self.decommission_dev_btn.setVisible(True)
        if dev_id:
            current_row = self.device_table.currentRow()
            status_item = self.device_table.item(current_row, 9)
            status = status_item.text().lower() if status_item else 'attivo'
            is_active = (status == 'attivo')
            self.edit_dev_btn.setEnabled(True)
            self.del_dev_btn.setEnabled(True)
            self.move_dev_btn.setEnabled(is_active)
            self.decommission_dev_btn.setVisible(is_active)
            self.decommission_dev_btn.setEnabled(is_active)
            self.reactivate_dev_btn.setVisible(not is_active)
            self.reactivate_dev_btn.setEnabled(not is_active)
            dev_desc = self.device_table.item(current_row, 1).text()
            serial = self.device_table.item(current_row, 3).text()
            self.verification_label.setText(f"STORICO VERIFICHE '{dev_desc.upper()}' - SN: '{serial.upper()}'")
            self.load_verifications_table(dev_id)
    
    def load_verifications_table(self, device_id):
        self.verifications_table.setRowCount(0)
        self.verifications_table.setSortingEnabled(False) 
        search_query = self.verification_search_box.text()
        verifications = services.get_verifications_for_device(device_id, search_query)
        for verif in verifications:
            row = self.verifications_table.rowCount()
            self.verifications_table.insertRow(row)
            self.verifications_table.setItem(row, 0, NumericTableWidgetItem(str(verif.get('id', 0))))
            self.verifications_table.setItem(row, 1, QTableWidgetItem(str(verif.get('verification_date')).upper()))
            status_item = QTableWidgetItem(str(verif.get('overall_status')).upper())
            status_item.setBackground(QColor('#A3BE8C') if verif.get('overall_status') == 'PASSATO' else QColor('#BF616A'))
            self.verifications_table.setItem(row, 2, status_item)
            profile_key = verif.get('profile_name', '')
            profile = config.PROFILES.get(profile_key)
            profile_display_name = profile.name if profile else profile_key
            self.verifications_table.setItem(row, 3, QTableWidgetItem(profile_display_name.upper()))
            self.verifications_table.setItem(row, 4, QTableWidgetItem(str(verif.get('technician_name', '')).upper()))
            self.verifications_table.setItem(row, 5, QTableWidgetItem(str(verif.get('verification_code', '')).upper()))
        self.set_verification_buttons_enabled(self.verifications_table.rowCount() > 0)
        self.verifications_table.setSortingEnabled(True)
        self.verifications_table.resizeRowsToContents()

    def add_customer(self):
        dialog = CustomerDialog(parent=self)
        if dialog.exec():
            try:
                services.add_customer(**dialog.get_data())
                self.load_customers_table()
            except ValueError as e:
                QMessageBox.warning(self, "DATI NON VALIDI", str(e).upper())

    def edit_customer(self):
        cust_id = self.get_selected_id(self.customer_table)
        if not cust_id:
            return
        customer_data = dict(services.database.get_customer_by_id(cust_id))
        dialog = CustomerDialog(customer_data, self)
        if dialog.exec():
            try:
                services.update_customer(cust_id, **dialog.get_data())
                self.load_customers_table()
            except ValueError as e:
                QMessageBox.warning(self, "DATI NON VALIDI", str(e).upper())

    def delete_customer(self):
        cust_id = self.get_selected_id(self.customer_table)
        if not cust_id:
            return
        reply = QMessageBox.question(self, 'CONFERMA', 'ELIMINARE IL CLIENTE E TUTTE LE SUE DESTINAZIONI E DISPOSITIVI?')
        if reply == QMessageBox.Yes:
            success, message = services.delete_customer(cust_id)
            if success:
                self.load_customers_table()
            else:
                QMessageBox.critical(self, "ERRORE", message.upper())

    def add_destination(self):
        cust_id = self.get_selected_id(self.customer_table)
        if not cust_id:
            return
        dialog = DestinationDetailDialog(parent=self)
        if dialog.exec():
            try:
                data = dialog.get_data()
                services.add_destination(cust_id, data['name'], data['address'])
                self.load_destinations_table(cust_id)
            except ValueError as e:
                QMessageBox.warning(self, "DATI NON VALIDI", str(e).upper())

    def edit_destination(self):
        dest_id = self.get_selected_id(self.destination_table)
        cust_id = self.get_selected_id(self.customer_table)
        if not dest_id or not cust_id:
            return
        dest_data = dict(services.database.get_destination_by_id(dest_id))
        dialog = DestinationDetailDialog(destination_data=dest_data, parent=self)
        if dialog.exec():
            try:
                data = dialog.get_data()
                services.update_destination(dest_id, data['name'], data['address'])
                self.load_destinations_table(cust_id)
            except ValueError as e:
                QMessageBox.warning(self, "DATI NON VALIDI", str(e).upper())

    def delete_destination(self):
        dest_id = self.get_selected_id(self.destination_table)
        cust_id = self.get_selected_id(self.customer_table)
        if not dest_id or not cust_id:
            return
        reply = QMessageBox.question(self, 'CONFERMA', 'ELIMINARE QUESTA DESTINAZIONE? (VERRANNO ELIMINATI ANCHE TUTTI I DISPOSITIVI AL SUO INTERNO)')
        if reply == QMessageBox.Yes:
            try:
                services.delete_destination(dest_id)
                self.load_destinations_table(cust_id)
            except ValueError as e:
                QMessageBox.critical(self, "ERRORE", str(e).upper())

    def add_device(self):
        cust_id = self.get_selected_id(self.customer_table)
        dest_id = self.get_selected_id(self.destination_table)
        if not dest_id or not cust_id:
            return QMessageBox.warning(self, "SELEZIONE MANCANTE", "SELEZIONA UN CLIENTE E UNA DESTINAZIONE.")
        dialog = DeviceDialog(customer_id=cust_id, destination_id=dest_id, parent=self)
        if dialog.exec():
            try:
                services.add_device(**dialog.get_data())
                self.load_devices_table(dest_id)
            except ValueError as e:
                QMessageBox.warning(self, "ERRORE VALIDAZIONE", str(e).upper())
                return
            except Exception as e:
                QMessageBox.critical(self, "ERRORE", f"IMPOSSIBILE SALVARE IL DISPOSITIVO:\n{str(e).upper()}")
                return

    def edit_device(self):
        cust_id = self.get_selected_id(self.customer_table)
        dev_id = self.get_selected_id(self.device_table)
        dest_id = self.get_selected_id(self.destination_table)
        if not dev_id or not cust_id or not dest_id:
            return
        device_data = dict(services.database.get_device_by_id(dev_id))
        dialog = DeviceDialog(customer_id=cust_id, device_data=device_data, parent=self)
        if dialog.exec():
            try:
                services.update_device(dev_id, **dialog.get_data())
                self.load_devices_table(dest_id)
            except ValueError as e:
                QMessageBox.warning(self, "ERRORE VALIDAZIONE", str(e).upper())
                return
            except Exception as e:
                QMessageBox.critical(self, "ERRORE", f"IMPOSSIBILE SALVARE IL DISPOSITIVO:\n{str(e).upper()}")
                return

    def delete_device(self):
        dev_id = self.get_selected_id(self.device_table)
        dest_id = self.get_selected_id(self.destination_table)
        if not dev_id or not dest_id:
            return
        reply = QMessageBox.question(self, 'CONFERMA', 'ELIMINARE QUESTO DISPOSITIVO E TUTTE LE SUE VERIFICHE?')
        if reply == QMessageBox.Yes:
            services.delete_device(dev_id)
            self.load_devices_table(dest_id)

    def move_device(self):
        dev_id = self.get_selected_id(self.device_table)
        old_dest_id = self.get_selected_id(self.destination_table)
        if not dev_id:
            return QMessageBox.warning(self, "SELEZIONE MANCANTE", "SELEZIONA UN DISPOSITIVO DA SPOSTARE.")
        dialog = DestinationSelectionDialog(self)
        if dialog.exec():
            new_dest_id = dialog.selected_destination_id
            if new_dest_id and new_dest_id != old_dest_id:
                try:
                    services.move_device_to_destination(dev_id, new_dest_id)
                    self.load_devices_table(old_dest_id)
                    QMessageBox.information(self, "SUCCESSO", "DISPOSITIVO SPOSTATO.")
                except Exception as e:
                    QMessageBox.critical(self, "ERRORE", f"IMPOSSIBILE SPOSTARE IL DISPOSITIVO: {str(e).upper()}")

    def import_from_file(self):
        dest_id = self.get_selected_id(self.destination_table)
        if not dest_id:
            return QMessageBox.warning(self, "SELEZIONE MANCANTE", "SELEZIONA UNA DESTINAZIONE IN CUI IMPORTARE.")
        filename, _ = QFileDialog.getOpenFileName(self, "SELEZIONA FILE", "", "File Excel/CSV (*.xlsx *.csv)")
        if not filename:
            return
        try:
            df_headers = pd.read_csv(filename, sep=';', dtype=str, nrows=0).columns.tolist() if filename.endswith('.csv') else pd.read_excel(filename, dtype=str, nrows=0).columns.tolist()
        except Exception as e:
            QMessageBox.critical(self, "ERRORE LETTURA FILE", f"IMPOSSIBILE LEGGERE LE INTESTAZIONI:\n{str(e).upper()}")
            return
        map_dialog = MappingDialog(df_headers, self)
        if map_dialog.exec() == QDialog.Accepted:
            mapping = map_dialog.get_mapping()
            if mapping is None:
                return
            self.progress_dialog = QProgressDialog("IMPORTAZIONE...", "ANNULLA", 0, 100, self)
            self.progress_dialog.setWindowModality(Qt.WindowModal)
            self.thread = QThread()
            self.worker = ImportWorker(filename, mapping, dest_id)
            self.worker.moveToThread(self.thread)
            self.worker.progress_updated.connect(self.progress_dialog.setValue)
            self.progress_dialog.canceled.connect(self.worker.cancel)
            self.thread.started.connect(self.worker.run)
            self.worker.finished.connect(self.on_import_finished)
            self.worker.error.connect(self.on_import_error)
            self.worker.finished.connect(self.thread.quit)
            self.worker.finished.connect(self.worker.deleteLater)
            self.thread.finished.connect(self.thread.deleteLater)
            self.thread.finished.connect(self.progress_dialog.close)
            self.thread.start()
            self.progress_dialog.exec()

    def on_import_finished(self, added_count, skipped_rows_details, status):
        dest_id = self.get_selected_id(self.destination_table)
        if dest_id:
            self.load_devices_table(dest_id)
        if status == "Annullato":
            QMessageBox.warning(self, "IMPORTAZIONE ANNULLATA", "OPERAZIONE ANNULLATA.")
            return
        summary = f"IMPORTAZIONE TERMINATA.\n- DISPOSITIVI AGGIUNTI: {added_count}\n- RIGHE IGNORATE: {len(skipped_rows_details)}"
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setWindowTitle("IMPORTAZIONE COMPLETATA")
        msg_box.setText(summary)
        if skipped_rows_details:
            details_button = msg_box.addButton("VISUALIZZA DETTAGLI...", QMessageBox.ActionRole)
        msg_box.addButton("OK", QMessageBox.AcceptRole)
        msg_box.exec()
        if skipped_rows_details and msg_box.clickedButton() == details_button:
            report_dialog = ImportReportDialog("DETTAGLIO RIGHE IGNORATE", skipped_rows_details, self)
            report_dialog.exec()

    def on_import_error(self, error_message):
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.close()
        QMessageBox.critical(self, "ERRORE DI IMPORTAZIONE", error_message.upper())

    def import_from_stm(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "SELEZIONA ARCHIVIO .STM", "", "File STM (*.stm)")
        if not filepath:
            return
        self.thread = QThread()
        self.worker = StmImportWorker(filepath)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_stm_import_finished)
        self.worker.error.connect(self.on_import_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.setWindowTitle("MANAGER ANAGRAFICHE (IMPORTAZIONE...)")
        self.thread.start()

    def on_stm_import_finished(self, verif_imported, verif_skipped, dev_new, cust_new):
        self.setWindowTitle("MANAGER ANAGRAFICHE")
        self.load_customers_table()
        QMessageBox.information(self, "IMPORTAZIONE COMPLETATA", f"IMPORTAZIONE DA ARCHIVIO COMPLETATA.\n- VERIFICHE IMPORTATE: {verif_imported}\n- VERIFICHE SALTATE: {verif_skipped}\n- NUOVI DISPOSITIVI: {dev_new}")

    def export_daily_verifications(self):
        date_dialog = DateSelectionDialog(self)
        if date_dialog.exec() == QDialog.Accepted:
            target_date = date_dialog.getSelectedDate()
            default_filename = f"Export_Verifiche_{target_date.replace('-', '')}.stm"
            output_path, _ = QFileDialog.getSaveFileName(self, "SALVA ESPORTAZIONE", default_filename, "File STM (*.stm)")
            if not output_path:
                return
            self.thread = QThread()
            self.worker = DailyExportWorker(target_date, output_path)
            self.worker.moveToThread(self.thread)
            self.thread.started.connect(self.worker.run)
            self.worker.finished.connect(self.on_export_finished)
            self.worker.error.connect(self.on_export_error)
            self.worker.finished.connect(self.thread.quit)
            self.worker.finished.connect(self.worker.deleteLater)
            self.thread.finished.connect(self.thread.deleteLater)
            self.setWindowTitle("MANAGER ANAGRAFICHE (ESPORTAZIONE...)")
            self.thread.start()

    def on_export_finished(self, status, message):
        self.setWindowTitle("MANAGER ANAGRAFICHE")
        if status == "Success":
            QMessageBox.information(self, "ESPORTAZIONE COMPLETATA", message.upper())
        else:
            QMessageBox.warning(self, "ESPORTAZIONE", message.upper())

    def on_export_error(self, error_message):
        self.setWindowTitle("MANAGER ANAGRAFICHE")
        QMessageBox.critical(self, "ERRORE ESPORTAZIONE", error_message.upper())

    def generate_monthly_reports(self):
        dest_id = self.get_selected_id(self.destination_table)
        if not dest_id: 
            return QMessageBox.warning(self, "Selezione Mancante", "Seleziona una destinazione.")
        period_dialog = SingleCalendarRangeDialog(self)
        if not period_dialog.exec(): 
            return
        start_date, end_date = period_dialog.get_date_range()
        verifications = services.database.get_verifications_for_destination_by_date_range(dest_id, start_date, end_date)
        if not verifications: 
            return QMessageBox.information(self, "NESSUNA VERIFICA", f"NESSUNA VERIFICA TROVATA NEL PERIODO SELEZIONATO.")
        output_folder = QFileDialog.getExistingDirectory(self, "SELEZIONA CARTELLA DI DESTINAZIONE PER I REPORT")
        if not output_folder: 
            return
        report_settings = {"logo_path": self.main_window.logo_path}
        self.progress_dialog = QProgressDialog("GENERAZIONE REPORT...", "ANNULLA", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.thread = QThread()
        self.worker = BulkReportWorker(verifications, output_folder, report_settings)
        self.worker.moveToThread(self.thread)
        self.progress_dialog.canceled.connect(self.worker.cancel)
        self.worker.progress_updated.connect(self.on_bulk_report_progress)
        self.worker.finished.connect(self.on_bulk_report_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.progress_dialog.close)
        self.thread.started.connect(self.worker.run)
        self.progress_dialog.show()
        self.thread.start()

    def on_bulk_report_progress(self, percent, message):
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.setValue(percent)
            self.progress_dialog.setLabelText(message)

    def on_bulk_report_finished(self, success_count, failed_reports):
        summary = f"GENERAZIONE COMPLETATA.\n- REPORT CREATI: {success_count}"
        if failed_reports:
            summary += f"\n- ERRORI: {len(failed_reports)}"
        msg_box = QMessageBox(QMessageBox.Information, "OPERAZIONE TERMINATA", summary, parent=self)
        if failed_reports:
            msg_box.setDetailedText("Dettaglio errori:\n" + "\n".join(failed_reports))
        msg_box.exec()

    def open_period_filter_dialog(self):
        dest_id = self.get_selected_id(self.destination_table)
        if not dest_id:
            return QMessageBox.warning(self, "Selezione Mancante", "Seleziona una destinazione.")
        date_dialog = SingleCalendarRangeDialog(self)
        if not date_dialog.exec():
            return
        start_date, end_date = date_dialog.get_date_range()
        try:
            verified, unverified = services.database.get_devices_verification_status_by_period(dest_id, start_date, end_date)
            results_dialog = VerificationStatusDialog(verified, unverified, self)
            results_dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "ERRORE", f"IMPOSSIBILE RECUPERARE LO STATO: {str(e).upper()}")
        
    def view_verification_details(self):
        verif_id = self.get_selected_id(self.verifications_table)
        dev_id = self.get_selected_id(self.device_table)
        if not verif_id or not dev_id:
            return
        all_verifs = services.get_verifications_for_device(dev_id)
        verif_data = next((v for v in all_verifs if v.get('id') == verif_id), None)
        if verif_data:
            dialog = VerificationViewerDialog(verif_data, self)
            dialog.exec()
        else:
            QMessageBox.critical(self, "ERRORE DATI", "IMPOSSIBILE TROVARE I DATI PER LA VERIFICA.")

    def generate_old_report(self):
        verif_id = self.get_selected_id(self.verifications_table)
        dev_id = self.get_selected_id(self.device_table)
        if not verif_id or not dev_id:
            return
        device_info = services.get_device_by_id(dev_id)
        if not device_info:
            return QMessageBox.critical(self, "ERRORE", "IMPOSSIBILE TROVARE I DATI DEL DISPOSITIVO.")
        ams_inv = device_info.get('ams_inventory', '').strip()
        serial_num = device_info.get('serial_number', '').strip()
        base_name = ams_inv if ams_inv else serial_num
        if not base_name:
            base_name = f"Report_Verifica_{verif_id}"
        safe_base_name = re.sub(r'[\\/*?:"<>|]', '_', base_name)
        default_filename = f"{safe_base_name} VE.pdf"
        filename, _ = QFileDialog.getSaveFileName(self, "SALVA REPORT PDF", default_filename, "PDF Files (*.pdf)")
        if not filename:
            return
        try:
            report_settings = {"logo_path": self.main_window.logo_path}
            services.generate_pdf_report(filename, verif_id, dev_id, report_settings)
            QMessageBox.information(self, "SUCCESSO", f"REPORT GENERATO CON SUCCESSO: {filename.upper()}")
        except Exception as e:
            QMessageBox.critical(self, "ERRORE", f"IMPOSSIBILE GENERARE IL REPORT: {str(e).upper()}")

    def print_old_report(self):
        verif_id = self.get_selected_id(self.verifications_table)
        dev_id = self.get_selected_id(self.device_table)
        if not verif_id or not dev_id:
            return
        try:
            report_settings = {"logo_path": self.main_window.logo_path}
            services.print_pdf_report(verif_id, dev_id, report_settings)
        except Exception as e:
            QMessageBox.critical(self, "ERRORE DI STAMPA", f"IMPOSSIBILE STAMPARE IL REPORT:\n{str(e).upper()}")

    def delete_verification(self):
        verif_id = self.get_selected_id(self.verifications_table)
        dev_id = self.get_selected_id(self.device_table)
        if not verif_id or not dev_id:
            return
        reply = QMessageBox.question(self, 'CONFERMA', f"SEI SICURO DI VOLER ELIMINARE LA VERIFICA ID {verif_id}?")
        if reply == QMessageBox.Yes:
            services.delete_verification(verif_id)
            self.load_verifications_table(dev_id)

    def show_all_customer_devices(self):
        cust_id = self.get_selected_id(self.customer_table)
        if not cust_id:
            return
        self.destination_table.clearSelection()
        customer_name = self.customer_table.item(self.customer_table.currentRow(), 1).text()
        self.device_label.setText(f"TUTTI I DISPOSITIVI PER '{customer_name.upper()}'")
        self.set_device_buttons_enabled(False)
        self.device_table.setSortingEnabled(False)
        self.device_table.setRowCount(0)
        search_text = self.device_search_box.text()
        devices = services.database.get_all_devices_for_customer(cust_id, search_text)
        for dev_row in devices:
            dev = dict(dev_row)
            row = self.device_table.rowCount()
            self.device_table.insertRow(row)
            status = dev.get('status', 'active')
            status_text = 'ATTIVO' if status == 'active' else 'DISMESSO'
            self.device_table.setItem(row, 0, QTableWidgetItem(str(dev.get('id'))))
            self.device_table.setItem(row, 1, QTableWidgetItem(str(dev.get('description')).upper()))
            self.device_table.setItem(row, 2, QTableWidgetItem(str(dev.get('department')).upper()))
            self.device_table.setItem(row, 3, QTableWidgetItem(str(dev.get('serial_number')).upper()))
            self.device_table.setItem(row, 4, QTableWidgetItem(str(dev.get('manufacturer')).upper()))
            self.device_table.setItem(row, 5, QTableWidgetItem(str(dev.get('model')).upper()))
            self.device_table.setItem(row, 6, QTableWidgetItem(str(dev.get('customer_inventory')).upper()))
            self.device_table.setItem(row, 7, QTableWidgetItem(str(dev.get('ams_inventory')).upper()))
            interval = dev.get('verification_interval')
            interval_text = str(interval) if interval is not None else "N/A"
            self.device_table.setItem(row, 8, QTableWidgetItem(interval_text.upper()))
            self.device_table.setItem(row, 9, QTableWidgetItem(status_text.upper()))
            if status == 'decommissioned':
                for col in range(self.device_table.columnCount()):
                    self.device_table.item(row, col).setForeground(QBrush(QColor("blue")))
        self.device_table.setSortingEnabled(True)
        self.device_table.resizeRowsToContents()
        self.tabs.setCurrentWidget(self.device_tab)
        
    def find_and_select_item(self, table: QTableWidget, item_id: int):
        for row in range(table.rowCount()):
            table_item = table.item(row, 0)
            if table_item and int(table_item.text()) == item_id:
                table.selectRow(row)
                table.scrollToItem(table_item, QAbstractItemView.ScrollHint.PositionAtCenter)
                break
    
    def export_destination_table(self):
        dest_id = self.get_selected_id(self.destination_table)
        if not dest_id:
            QMessageBox.warning(self, "SELEZIONE MANCANTE", "SELEZIONA UNA DESTINAZIONE PER CUI GENERARE LA TABELLA.")
            return

        date_dialog = SingleCalendarRangeDialog(self)
        if date_dialog.exec() == QDialog.Accepted:
            start_date_obj, end_date_obj = date_dialog.get_date_range()
            if not start_date_obj or not end_date_obj:
                QMessageBox.warning(self, "SELEZIONE MANCANTE", "DEVI SELEZIONARE UN INTERVALLO DI DATE VALIDO.")
                return
            
            start_date = start_date_obj.toString("yyyy-MM-dd") if hasattr(start_date_obj, 'toString') else str(start_date_obj)
            end_date = end_date_obj.toString("yyyy-MM-dd") if hasattr(end_date_obj, 'toString') else str(end_date_obj)
            
            destination_name = self.destination_table.item(self.destination_table.currentRow(), 1).text()
            safe_name = re.sub(r'[\\/*?:"<>|]', '_', f"{destination_name}_{start_date}_al_{end_date}")
            default_filename = f"Tabella Verifiche_{safe_name}.xlsx"

            output_path, _ = QFileDialog.getSaveFileName(self, "SALVA TABELLA EXCEL", default_filename, "File Excel (*.xlsx)")
            if not output_path:
                return

            self.thread = QThread()
            self.worker = TableExportWorker(dest_id, output_path, start_date, end_date)
            self.worker.moveToThread(self.thread)

            self.thread.started.connect(self.worker.run)
            self.worker.finished.connect(self.on_table_export_finished)
            self.worker.error.connect(self.on_table_export_error)
            self.worker.finished.connect(self.thread.quit)
            self.worker.finished.connect(self.worker.deleteLater)
            self.thread.finished.connect(self.thread.deleteLater)
            
            self.setWindowTitle("MANAGER ANAGRAFICHE (ESPORTAZIONE TABELLA...)")
            self.thread.start()

    def on_table_export_finished(self, message):
        self.setWindowTitle("MANAGER ANAGRAFICHE")
        QMessageBox.information(self, "ESPORTAZIONE COMPLETATA", message.upper())

    def on_table_export_error(self, error_message):
        self.setWindowTitle("MANAGER ANAGRAFICHE")
        QMessageBox.critical(self, "ERRORE ESPORTAZIONE", error_message.upper())

# --- Classe InstrumentManagerDialog (inclusa per completezza) ---
class InstrumentManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GESTIONE ANAGRAFICA STRUMENTI")
        self.setMinimumSize(800, 500)
        self.setStyleSheet(config.MODERN_STYLESHEET)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "NOME STRUMENTO", "SERIALE", "VERSIONE FW", "DATA CAL."])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader(); header.setSectionResizeMode(0, QHeaderView.ResizeToContents); header.setSectionResizeMode(1, QHeaderView.Stretch); header.setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table)
        buttons_layout = QHBoxLayout()
        add_btn = QPushButton("AGGIUNGI"); add_btn.clicked.connect(self.add_instrument)
        edit_btn = QPushButton("MODIFICA"); edit_btn.clicked.connect(self.edit_instrument)
        delete_btn = QPushButton("ELIMINA"); delete_btn.clicked.connect(self.delete_instrument)
        default_btn = QPushButton("IMPOSTA COME PREDEFINITO"); default_btn.clicked.connect(self.set_default)
        buttons_layout.addWidget(add_btn); buttons_layout.addWidget(edit_btn); buttons_layout.addWidget(delete_btn); buttons_layout.addStretch(); buttons_layout.addWidget(default_btn)
        layout.addLayout(buttons_layout)
        self.load_instruments()

    def get_selected_id(self) -> int | None:
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows: return None
        try: return int(self.table.item(selected_rows[0].row(), 0).text())
        except (ValueError, AttributeError): return None

    def load_instruments(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        instruments_rows = services.get_all_instruments()
        for inst_row in instruments_rows:
            instrument = dict(inst_row); row = self.table.rowCount(); self.table.insertRow(row)
            id_item = QTableWidgetItem(str(instrument.get('id'))); id_item.setFlags(id_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, id_item); self.table.setItem(row, 1, QTableWidgetItem(str(instrument.get('instrument_name', '')).upper())); self.table.setItem(row, 2, QTableWidgetItem(str(instrument.get('serial_number', '')).upper())); self.table.setItem(row, 3, QTableWidgetItem(str(instrument.get('fw_version', '')).upper())); self.table.setItem(row, 4, QTableWidgetItem(str(instrument.get('calibration_date', '')).upper()))
            if instrument.get('is_default'):
                for col in range(5): self.table.item(row, col).setBackground(QColor("#E0F7FA"))
        self.table.setSortingEnabled(True)

    def add_instrument(self):
        dialog = InstrumentDetailDialog(parent=self)
        if dialog.exec():
            try: 
                services.add_instrument(**dialog.get_data())
                self.load_instruments()
            except ValueError as e: 
                QMessageBox.warning(self, "DATI NON VALIDI", str(e).upper())

    def edit_instrument(self):
        inst_id = self.get_selected_id()
        if not inst_id: return
        all_instruments = services.get_all_instruments()
        inst_row = next((inst for inst in all_instruments if inst['id'] == inst_id), None)
        inst_data_dict = dict(inst_row) if inst_row else None
        dialog = InstrumentDetailDialog(inst_data_dict, self)
        if dialog.exec():
            try: 
                services.update_instrument(inst_id, **dialog.get_data())
                self.load_instruments()
            except ValueError as e: 
                QMessageBox.warning(self, "DATI NON VALIDI", str(e).upper())

    def delete_instrument(self):
        inst_id = self.get_selected_id()
        if not inst_id: return
        reply = QMessageBox.question(self, "CONFERMA ELIMINAZIONE", "SEI SICURO DI VOLER ELIMINARE LO STRUMENTO SELEZIONATO?")
        if reply == QMessageBox.Yes: 
            services.delete_instrument(inst_id)
            self.load_instruments()
            
    def set_default(self):
        inst_id = self.get_selected_id()
        if not inst_id: return
        services.set_default_instrument(inst_id)
        self.load_instruments()