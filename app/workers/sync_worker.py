# app/workers/sync_worker.py (Versione con logica di Retry)
from PySide6.QtCore import QObject, Signal
from app import sync_manager
import logging
import time # Importa il modulo 'time'

class SyncWorker(QObject):
    finished = Signal(str)
    error = Signal(str)
    conflict = Signal(list)

    def __init__(self, full_sync=False):
        super().__init__()
        self.full_sync = full_sync

    def run(self):
        """
        Esegue la sincronizzazione in un thread separato,
        con una logica di re-tentativo in caso di errori.
        """
        max_retries = 3      # Numero massimo di tentativi
        retry_delay = 10     # Secondi di attesa tra un tentativo e l'altro

        logging.info(f"SyncWorker avviato (Sincronizzazione Completa: {self.full_sync}).")

        for attempt in range(max_retries):
            try:
                logging.info(f"Tentativo di sincronizzazione {attempt + 1} di {max_retries}...")
                
                # Chiama la funzione principale che ora gestisce il locking
                status, data = sync_manager.run_sync(full_sync=self.full_sync)
                
                # Se 'status' è None, significa che la sync è bloccata.
                # Il worker termina silenziosamente perché l'utente è già stato avvisato.
                if status is None:
                    logging.warning("Sincronizzazione già in corso. Il worker si arresta.")
                    return

                if status == "success":
                    logging.info(f"Sincronizzazione completata con successo al tentativo {attempt + 1}.")
                    self.finished.emit(data)
                    return  # Esce dalla funzione con successo

                if status == "conflict":
                    logging.warning(f"Conflitto di sincronizzazione rilevato al tentativo {attempt + 1}.")
                    self.conflict.emit(data)
                    return  # Esce: il conflitto richiede un intervento, non un re-tentativo

                # Se status == "error", il ciclo continuerà per un altro tentativo
                logging.warning(f"Tentativo {attempt + 1} fallito con errore gestito: {data}")

                # Se è l'ultimo tentativo, emette l'errore e termina
                if attempt == max_retries - 1:
                    logging.error("Numero massimo di tentativi raggiunto. Sincronizzazione fallita.")
                    self.error.emit(data)
                    return

                logging.info(f"Nuovo tentativo tra {retry_delay} secondi...")
                time.sleep(retry_delay)
                
            except Exception as e:
                # Questo blocco gestisce errori imprevisti non catturati da sync_manager
                logging.error(f"Errore imprevisto nel worker al tentativo {attempt + 1}.", exc_info=True)
                
                if attempt == max_retries - 1:
                    self.error.emit(f"Errore imprevisto dopo {max_retries} tentativi: {str(e)}")
                    return
                
                time.sleep(retry_delay)