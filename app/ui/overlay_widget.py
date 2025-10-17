# app/ui/widgets/overlay_widget.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtGui import QMovie, QColor, QPalette
from PySide6.QtCore import Qt, QSize

class OverlayWidget(QWidget):
    """
    Un widget semitrasparente che si sovrappone a un widget genitore
    per mostrare un messaggio e un'animazione di caricamento.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        # Layout per centrare il contenuto
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        # Animazione "spinner"
        self.spinner_label = QLabel(self)
        # Assicurati di avere un file GIF chiamato 'loading.gif' nella cartella 'icons'
        # Puoi scaricarne uno da siti come https://loading.io/
        self.movie = QMovie("./icons/loading.gif")
        self.movie.setScaledSize(QSize(300, 300)) # Imposta una dimensione fissa per lo spinner
        self.spinner_label.setMovie(self.movie)
        
        # Messaggio di testo
        self.message_label = QLabel("Operazione in corso...", self)
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 20px;
                font-weight: bold;
                background-color: rgba(0, 0, 0, 180);
                border: none;
            }
        """)

        layout.addWidget(self.spinner_label)
        layout.addSpacing(15)
        layout.addWidget(self.message_label)

        # Nascondi il widget all'inizio
        self.hide()

    def setText(self, text: str):
        """Imposta il testo da visualizzare sull'overlay."""
        self.message_label.setText(text)

    def show(self):
        """Mostra l'overlay e avvia l'animazione."""
        self.movie.start()
        super().show()

    def hide(self):
        """Nasconde l'overlay e ferma l'animazione."""
        self.movie.stop()
        super().hide()