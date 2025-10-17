import json
from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QMessageBox, QGridLayout,
    QVBoxLayout, QGroupBox, QTableWidget, QTableWidgetItem, QHBoxLayout, QComboBox, QPushButton, QApplication, QStyle, QLabel, QHeaderView, QAbstractItemView, QCompleter)
from PySide6.QtCore import Qt, QStringListModel
from app.data_models import AppliedPart
from app.hardware.fluke_esa612 import FlukeESA612
import logging
from app.ui.dialogs.utility_dialogs import DeviceSearchDialog
from app import services
import database  # Import your database module

class CustomerDialog(QDialog):
    def __init__(self, customer_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dettagli Cliente")
        data = customer_data or {}
        layout = QFormLayout(self)
        self.name_edit = QLineEdit(data.get('name', ''))
        self.address_edit = QLineEdit(data.get('address', ''))
        self.phone_edit = QLineEdit(data.get('phone', ''))
        self.email_edit = QLineEdit(data.get('email', ''))
        layout.addRow("Nome:", self.name_edit)
        layout.addRow("Indirizzo:", self.address_edit)
        layout.addRow("Telefono:", self.phone_edit)
        layout.addRow("Email:", self.email_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        return { "name": self.name_edit.text().strip(), "address": self.address_edit.text().strip(),
                 "phone": self.phone_edit.text().strip(), "email": self.email_edit.text().strip() }
    
class DeviceDialog(QDialog):
    def __init__(self, customer_id, destination_id=None, device_data=None, is_copy=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dettagli Dispositivo")
        self.resize(1300, 930)
        
        self.AP_CODE_SEQUENCE = ["RA", "LA", "LL", "RL", "V1", "V2", "V3", "V4", "V5", "V6"]
        
        data = device_data or {}
        self.customer_id = customer_id
        self.destination_id = destination_id

        main_layout = QVBoxLayout(self)
        
        self.copy_button = QPushButton("COPIA DATI DA UN DISPOSITIVO ESISTENTE...")
        self.copy_button.setIcon(QApplication.style().standardIcon(QStyle.SP_DialogResetButton))
        self.copy_button.clicked.connect(self.open_copy_search)
        main_layout.addWidget(self.copy_button)
        
        if device_data and not is_copy:
            self.copy_button.hide()
        
        if is_copy:
            data['serial_number'] = ''
            data['customer_inventory'] = ''
            data['ams_inventory'] = ''

        self.profile_combo = QComboBox()
        # Popoliamo il ComboBox con i profili caricati all'avvio
        from app import config
        for key, profile in config.PROFILES.items():
            self.profile_combo.addItem(profile.name, key) # Mostra il nome, ma salva la chiave

        # Se siamo in modalità modifica, preselezioniamo il profilo salvato
        if device_data and device_data.get('default_profile_key'):
            profile_key_to_select = device_data['default_profile_key']
            index = self.profile_combo.findData(profile_key_to_select)
            if index != -1:
                self.profile_combo.setCurrentIndex(index)

        self.destination_combo = QComboBox()
        destinations = services.database.get_destinations_for_customer(self.customer_id)
        for dest in destinations:
            self.destination_combo.addItem(dest['name'], dest['id'])
    
        id_to_select = device_data.get('destination_id') if device_data else destination_id
        if id_to_select is not None:
            index = self.destination_combo.findData(id_to_select)
            if index != -1:
                self.destination_combo.setCurrentIndex(index)
        if device_data and device_data.get('destination_id'):
            destination_id_to_select = device_data['destination_id']
        
            # 1. Trova l'indice dell'elemento che ha il 'destination_id' corretto
            index = self.destination_combo.findData(destination_id_to_select)
        
            # 2. Se l'indice è valido (diverso da -1), impostalo come corrente
            if index != -1:
                self.destination_combo.setCurrentIndex(index)

        # --- LAYOUT A GRIGLIA A DUE COLONNE ---
        grid_layout = QGridLayout()
        grid_layout.setSpacing(10)
        
        self.serial_edit = QLineEdit(data.get('serial_number', ''))
        self.desc_edit = QLineEdit(data.get('description', ''))
        self.setup_description_completer()
        self.mfg_edit = QLineEdit(data.get('manufacturer', '').upper())
        self.model_edit = QLineEdit(data.get('model', '').upper())
        self.department_edit = QLineEdit(data.get('department', ''))
        self.ams_inv_edit = QLineEdit(data.get('ams_inventory', ''))
        self.customer_inv_edit = QLineEdit(data.get('customer_inventory', ''))
        
        self.verification_interval_combo = QComboBox()
        self.verification_interval_combo.addItems(["Nessuno", "6", "12", "24", "36"])
        if data.get('verification_interval') is not None:
            self.verification_interval_combo.setCurrentText(str(data['verification_interval']))

        # Riga 0
        grid_layout.addWidget(QLabel("DESTINAZIONE / SEDE:"), 0, 0, 1, 4)
        grid_layout.addWidget(self.destination_combo, 1, 0, 1, 4)
        # Riga 2
        grid_layout.addWidget(QLabel("DESCRIZIONE:"), 2, 0); grid_layout.addWidget(self.desc_edit, 2, 1)
        grid_layout.addWidget(QLabel("COSTRUTTORE:"), 2, 2); grid_layout.addWidget(self.mfg_edit, 2, 3)
        # Riga 3
        grid_layout.addWidget(QLabel("MODELLO:"), 3, 0); grid_layout.addWidget(self.model_edit, 3, 1)
        grid_layout.addWidget(QLabel("NUMERO DI SERIE:"), 3, 2); grid_layout.addWidget(self.serial_edit, 3, 3)
        # Riga 4
        grid_layout.addWidget(QLabel("REPARTO (DETTAGLIO):"), 4, 0); grid_layout.addWidget(self.department_edit, 4, 1)
        grid_layout.addWidget(QLabel("PROFILO DI VERIFICA DEFAULT:"), 4, 2); grid_layout.addWidget(self.profile_combo, 4, 3)
        # Riga 5
        grid_layout.addWidget(QLabel("INVENTARIO AMS:"), 5, 0); grid_layout.addWidget(self.ams_inv_edit, 5, 1)
        grid_layout.addWidget(QLabel("INVENTARIO CLIENTE:"), 5, 2); grid_layout.addWidget(self.customer_inv_edit, 5, 3)
        # Riga 6
        grid_layout.addWidget(QLabel("INTERVALLO VERIFICA (MESI):"), 6, 0); grid_layout.addWidget(self.verification_interval_combo, 6, 1)

        main_layout.addLayout(grid_layout)
        
        pa_group = QGroupBox("PARTI APPLICATE")
        pa_layout = QVBoxLayout(pa_group)
        self.applied_parts = [AppliedPart(**pa_data) for pa_data in data.get('applied_parts', [])]
        self.pa_table = QTableWidget(0, 3)
        self.pa_table.setHorizontalHeaderLabels(["NOME DESCRITTIVO", "TIPO", "CODICE STRUMENTO"])
        pa_layout.addWidget(self.pa_table)
        
        # --- Layout per i pulsanti di gestione P.A. ---
        add_pa_layout = QHBoxLayout()
        self.pa_name_input = QLineEdit()
        self.pa_name_input.setPlaceholderText("Nome descrittivo (es. ECG Torace)")
        
        self.pa_type_selector = QComboBox()
        self.pa_type_selector.addItems(["B", "BF", "CF"])
        
        add_pa_btn = QPushButton("AGGIUNGI P.A.")
        add_pa_btn.clicked.connect(self.add_pa)
        
        add_pa_layout.addWidget(QLabel("NOME:"))
        add_pa_layout.addWidget(self.pa_name_input)
        add_pa_layout.addWidget(QLabel("TIPO:"))
        add_pa_layout.addWidget(self.pa_type_selector)
        add_pa_layout.addWidget(add_pa_btn)
        
        pa_layout.addLayout(add_pa_layout)

        delete_pa_layout = QHBoxLayout()
        delete_pa_btn = QPushButton("Elimina P.A. Selezionata")
        delete_pa_btn.setIcon(QApplication.style().standardIcon(QStyle.SP_TrashIcon))
        delete_pa_btn.clicked.connect(self.delete_pa)
        delete_pa_layout.addStretch()
        delete_pa_layout.addWidget(delete_pa_btn)
        pa_layout.addLayout(delete_pa_layout)

        main_layout.addWidget(pa_group)
        self.load_pa_table()
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        # Crea e configura i completer
        self.manufacturer_completer = QCompleter(self)
        self.model_completer = QCompleter(self)

        # Imposta le proprietà dei completer
        for completer in [self.manufacturer_completer, self.model_completer]:
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            completer.setCompletionMode(QCompleter.PopupCompletion)

        # Assegna i completer ai campi
        self.mfg_edit.setCompleter(self.manufacturer_completer)
        self.model_edit.setCompleter(self.model_completer)

        # Carica i dati per l'autocompletamento
        self.load_completion_data()

    def load_completion_data(self):
        """Carica i dati per l'autocompletamento."""
        try:
            # Query per costruttori
            manufacturers = services.get_unique_manufacturers()
            manufacturer_list = sorted(list(set(m['manufacturer'].upper() for m in manufacturers if m['manufacturer'])))
            manufacturer_model = QStringListModel(manufacturer_list)
            self.manufacturer_completer.setModel(manufacturer_model)

            # Query per modelli
            models = services.get_unique_models()
            model_list = sorted(list(set(m['model'].upper() for m in models if m['model'])))
            model_model = QStringListModel(model_list)
            self.model_completer.setModel(model_model)

        except Exception as e:
            logging.error(f"Errore nel caricamento dei dati di completamento: {e}")

    def setup_description_completer(self):
        """Imposta l'autocompletamento per il campo descrizione."""
        try:
            descriptions = services.get_all_unique_device_descriptions()
            completer = QCompleter(descriptions, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            self.desc_edit.setCompleter(completer)
        except Exception as e:
            logging.error(f"Impossibile caricare i suggerimenti per la descrizione: {e}")

    def add_pa(self):
        """Aggiunge una parte applicata assegnando il codice successivo nella sequenza."""
        name = self.pa_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "DATI MANCANTI", "INSERIRE UN NOME DESCRITTIVO PER LA PARTE APPLICATA.")
            return

        next_code_index = len(self.applied_parts)
        if next_code_index >= len(self.AP_CODE_SEQUENCE):
            QMessageBox.critical(self, "LIMITE RAGGIUNTO", f"NON È POSSIBILE AGGIUNGERE PIÙ DI {len(self.AP_CODE_SEQUENCE)} PARTI APPLICATE.")
            return
            
        assigned_code = self.AP_CODE_SEQUENCE[next_code_index]

        self.applied_parts.append(AppliedPart(
            name=name, 
            part_type=self.pa_type_selector.currentText(),
            code=assigned_code
        ))
        self.load_pa_table()
        self.pa_name_input.clear()

    def delete_pa(self):
        """Elimina la parte applicata selezionata dalla tabella."""
        current_row = self.pa_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "SELEZIONE MANCANTE", "SELEZIONARE UNA PARTE APPLICATA DA ELIMINARE.")
            return
        
        part_to_delete = self.applied_parts[current_row]
        reply = QMessageBox.question(self, "CONFERMA ELIMINAZIONE", 
                                     f"SEI SICURO DI VOLER ELIMINARE LA PARTE APPLICATA '{part_to_delete.name.upper()}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.applied_parts.pop(current_row)
            self.load_pa_table()

    def load_pa_table(self):
        """Ricarica la tabella e riassegna i codici sequenziali."""
        # Riassegna i codici per mantenere la sequenza corretta
        for i, part in enumerate(self.applied_parts):
            if i < len(self.AP_CODE_SEQUENCE):
                part.code = self.AP_CODE_SEQUENCE[i]

        self.pa_table.setRowCount(0)
        for pa in self.applied_parts:
            row = self.pa_table.rowCount()
            self.pa_table.insertRow(row)
            self.pa_table.setItem(row, 0, QTableWidgetItem(pa.name.upper()))
            self.pa_table.setItem(row, 1, QTableWidgetItem(pa.part_type.upper()))
            self.pa_table.setItem(row, 2, QTableWidgetItem(pa.code.upper()))

    def open_copy_search(self):
        """Apre la dialog di ricerca e popola i campi con i dati del dispositivo scelto."""
        search_dialog = DeviceSearchDialog(self)
        if search_dialog.exec():
            template_data = search_dialog.selected_device_data
            if template_data:
                self.populate_fields(template_data)

    def populate_fields(self, data):
        """Popola i campi della dialog con i dati forniti."""
        # Popola i campi principali (descrizione, modello, ecc.)
        self.desc_edit.setText(data.get('description', ''))
        self.mfg_edit.setText(data.get('manufacturer', ''))
        self.model_edit.setText(data.get('model', ''))
        
        # Lascia vuoti i campi univoci
        self.serial_edit.clear()
        self.customer_inv_edit.clear()
        self.ams_inv_edit.clear()
        
        # Imposta l'intervallo di verifica
        interval = data.get('verification_interval')
        if interval is not None:
            self.verification_interval_combo.setCurrentText(str(interval))
        else:
            self.verification_interval_combo.setCurrentText("Nessuno")
            
        # Popola le parti applicate
        self.applied_parts = []
        for pa_data in data.get('applied_parts', []):
            self.applied_parts.append(AppliedPart(**pa_data))
        self.load_pa_table()

        # Metti il focus sul primo campo da compilare
        self.serial_edit.setFocus()


    def get_data(self):
        return { 
            "destination_id": self.destination_combo.currentData(),
            "default_profile_key": self.profile_combo.currentData(),
            "serial": self.serial_edit.text().strip().upper(), 
            "desc": self.desc_edit.text().strip().upper(),
            "mfg": self.mfg_edit.text().strip().upper(), 
            "model": self.model_edit.text().strip().upper(),
            "department": self.department_edit.text().strip().upper(),
            "customer_inv": self.customer_inv_edit.text().strip().upper(), 
            "ams_inv": self.ams_inv_edit.text().strip().upper(),
            "applied_parts": self.applied_parts, 
            "verification_interval": self.verification_interval_combo.currentText() 
        }
    
class InstrumentDetailDialog(QDialog):
    """Dialog per inserire/modificare i dettagli di un singolo strumento."""
    def __init__(self, instrument_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DETTAGLI STRUMENTO DI MISURA")
        data = instrument_data or {}
        layout = QFormLayout(self)

        # 1. Creazione di tutti i widget
        self.name_edit = QLineEdit(data.get('instrument_name', ''))
        self.serial_edit = QLineEdit(data.get('serial_number', ''))
        self.version_edit = QLineEdit(data.get('fw_version', ''))
        self.cal_date_edit = QLineEdit(data.get('calibration_date', ''))
        
        # 2. Aggiunta dei widget al layout
        layout.addRow("NOME STRUMENTO:", self.name_edit)
        layout.addRow("NUMERO DI SERIE:", self.serial_edit)
        layout.addRow("VERSIONE FIRMWARE:", self.version_edit)
        layout.addRow("DATA CALIBRAZIONE:", self.cal_date_edit)
        
        # 4. Aggiunta dei pulsanti finali
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        return {
            "instrument_name": self.name_edit.text().strip().upper(),
            "serial_number": self.serial_edit.text().strip().upper(),
            "fw_version": self.version_edit.text().strip().upper(),
            "calibration_date": self.cal_date_edit.text().strip().upper(),
        }
