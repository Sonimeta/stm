# app/ui/dialogs/advanced_search_dialog.py

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QGridLayout, QLabel, QLineEdit,
                               QPushButton, QTableWidget, QHeaderView, QAbstractItemView, QDateEdit,
                               QMessageBox, QTableWidgetItem, QComboBox, QCheckBox, QHBoxLayout)
from PySide6.QtCore import Qt, QDate
from app import services
from app.ui.dialogs.utility_dialogs import SingleCalendarRangeDialog

class AdvancedSearchDialog(QDialog):
    """
    Finestra di dialogo per la ricerca avanzata di dispositivi e verifiche.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RICERCA AVANZATA")
        self.setMinimumSize(1000, 700)

        # Layout principale
        layout = QVBoxLayout(self)

        # --- Sezione Criteri di Ricerca ---
        grid_layout = QGridLayout()
        grid_layout.setSpacing(10)

        self.customer_input = QLineEdit()
        self.destination_input = QLineEdit()
        self.device_desc_input = QLineEdit()
        self.serial_number_input = QLineEdit()
        self.manufacturer_input = QLineEdit()
        self.model_input = QLineEdit()
        self.technician_input = QLineEdit()
        self.outcome_combo = QComboBox()
        self.outcome_combo.addItems(["QUALSIASI", "CONFORME", "NON CONFORME", "NON VERIFICATO"])

        self.date_range_button = QPushButton("SELEZIONA INTERVALLO...")
        self.date_range_button.clicked.connect(self._select_date_range)
        self.date_range_label = QLabel("NESSUN INTERVALLO SELEZIONATO")
        self.start_date = None
        self.end_date = None

        grid_layout.addWidget(QLabel("CLIENTE:"), 0, 0)
        grid_layout.addWidget(self.customer_input, 0, 1)
        grid_layout.addWidget(QLabel("DESTINAZIONE:"), 0, 2)
        grid_layout.addWidget(self.destination_input, 0, 3)

        grid_layout.addWidget(QLabel("APPARECCHIO:"), 1, 0)
        grid_layout.addWidget(self.device_desc_input, 1, 1)
        grid_layout.addWidget(QLabel("MATRICOLA:"), 1, 2)
        grid_layout.addWidget(self.serial_number_input, 1, 3)

        grid_layout.addWidget(QLabel("MARCA:"), 2, 0)
        grid_layout.addWidget(self.manufacturer_input, 2, 1)
        grid_layout.addWidget(QLabel("MODELLO:"), 2, 2)
        grid_layout.addWidget(self.model_input, 2, 3)

        grid_layout.addWidget(QLabel("TECNICO:"), 3, 0)
        grid_layout.addWidget(self.technician_input, 3, 1)
        grid_layout.addWidget(QLabel("ESITO VERIFICA:"), 3, 2)
        grid_layout.addWidget(self.outcome_combo, 3, 3)

        date_layout = QHBoxLayout()
        date_layout.addWidget(self.date_range_button)
        date_layout.addWidget(self.date_range_label)
        date_layout.addStretch()
        grid_layout.addWidget(QLabel("PERIODO VERIFICA:"), 4, 0)
        grid_layout.addLayout(date_layout, 4, 1, 1, 2)

        self.search_button = QPushButton("CERCA")
        self.search_button.clicked.connect(self._perform_search)
        grid_layout.addWidget(self.search_button, 4, 3)

        layout.addLayout(grid_layout)

        # --- Tabella dei Risultati ---
        self.results_table = QTableWidget()
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setAlternatingRowColors(True)
        layout.addWidget(self.results_table)

    def _select_date_range(self):
        dialog = SingleCalendarRangeDialog(self)
        if dialog.exec():
            self.start_date, self.end_date = dialog.get_date_range()
            if self.start_date and self.end_date:
                start = QDate.fromString(self.start_date, "yyyy-MM-dd").toString("dd/MM/yy")
                end = QDate.fromString(self.end_date, "yyyy-MM-dd").toString("dd/MM/yy")
                self.date_range_label.setText(f"DAL <b>{start}</b> AL <b>{end}</b>")


    def _perform_search(self):
        """
        Esegue la ricerca in base ai criteri inseriti e popola la tabella.
        """
        criteria = {
            "customer_name": self.customer_input.text().strip(),
            "destination_name": self.destination_input.text().strip(),
            "device_description": self.device_desc_input.text().strip(),
            "serial_number": self.serial_number_input.text().strip(),
            "manufacturer": self.manufacturer_input.text().strip(),
            "model": self.model_input.text().strip(),
            "technician_name": self.technician_input.text().strip(),
            "outcome": self.outcome_combo.currentText(),
            "start_date": self.start_date,
            "end_date": self.end_date,
        }

        try:
            results = services.advanced_search(criteria)
            self._populate_table(results)
        except Exception as e:
            QMessageBox.critical(self, "ERRORE", f"SI È VERIFICATO UN ERRORE DURANTE LA RICERCA:\n{str(e).upper()}")

    def _populate_table(self, data):
        """
        Popola la tabella dei risultati con i dati forniti.
        """
        if not data:
            self.results_table.setRowCount(0)
            self.results_table.setColumnCount(0)
            QMessageBox.information(self, "NESSUN RISULTATO", "LA RICERCA NON HA PRODOTTO RISULTATI.")
            return

        headers = list(data[0].keys())
        self.results_table.setColumnCount(len(headers))
        self.results_table.setHorizontalHeaderLabels([h.upper() for h in headers])
        self.results_table.setRowCount(len(data))

        for row_idx, row_data in enumerate(data):
            for col_idx, key in enumerate(headers):
                item = QTableWidgetItem(str(row_data[key] if row_data[key] is not None else "").upper())
                self.results_table.setItem(row_idx, col_idx, item)

        self.results_table.resizeColumnsToContents()
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)