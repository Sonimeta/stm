from click import command
import serial
import serial.tools.list_ports
import time
import logging
import re

class FlukeESA612Error(Exception):
    """Eccezione personalizzata per errori di comunicazione con il Fluke ESA612."""
    pass
# Dizionario per tradurre i codici di errore dello strumento
FLUKE_ERROR_CODES = {
    "!56": "Tensione di rete assente (Mains not present). Assicurarsi che il dispositivo da testare sia acceso e collegato.",
    "!21": "Cavo di terra o presa apparecchio non collegato allo strumento."
}

class FlukeESA612:
    def __init__(self, port):
        if not port or port == "Nessuna":
            raise ValueError("È richiesta una porta COM valida per comunicare con lo strumento.")
        self.port = port
        self.ser = None
        self.connection_params = {
            'baudrate': 115200, 'bytesize': serial.EIGHTBITS, 'parity': serial.PARITY_NONE,
            'stopbits': serial.STOPBITS_ONE, 'timeout': 4, 'rtscts': True
        }

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def connect(self):
        try:
            logging.info(f"Connessione con strumento sulla porta {self.port}...")
            self.ser = serial.Serial(self.port, **self.connection_params)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            time.sleep(0.2) # Breve pausa per stabilizzare la connessione
            self.ser.write(b'\x1b') # Invia ESC per resettare lo stato dello strumento
            time.sleep(0.2)  # Dai allo strumento il tempo di rispondere a ESC
            
            # Svuota attivamente il buffer di input da qualsiasi risposta residua a ESC
            if self.ser.in_waiting > 0:
                bytes_da_leggere = self.ser.in_waiting
                self.ser.read(bytes_da_leggere)
                logging.debug(f"Puliti {bytes_da_leggere} byte residui dopo ESC.")
            
            self.ser.reset_input_buffer() # Assicura che sia completamente vuoto
            
            self._send_and_check("REMOTE")
            time.sleep(0.2)
            logging.info("Connessione riuscita e strumento in modalità remota.")
            
        except serial.SerialException as e:
            raise ConnectionError(f"Impossibile aprire la porta {self.port}. Controllare che sia libera e che lo strumento sia acceso.")
        except Exception:
            self.disconnect()
            raise

    def disconnect(self):
        """
        Riporta lo strumento in modalità locale e chiude la connessione in modo definitivo.
        """
        if self.ser and self.ser.is_open:
            try:
                logging.info("Ripristino dello strumento in modalità locale...")
                # Pulisce eventuali dati residui nel buffer prima di inviare l'ultimo comando
                if self.ser.in_waiting > 0:
                    self.ser.read(self.ser.in_waiting)
                    logging.debug("Puliti byte residui prima della disconnessione.")

                self.ser.write(b'LOCAL\r\n')
                logging.debug("-> CMD: LOCAL")
                time.sleep(0.5) # Pausa critica per permettere allo strumento di tornare in locale
            except Exception as e:
                logging.warning(f"Errore non critico durante l'invio del comando LOCAL: {e}")
            finally:
                self.ser.close()
                logging.info(f"Disconnesso da {self.port}.")
        self.ser = None

    def send_command(self, command: str) -> str:
        if not self.ser or not self.ser.is_open:
            raise ConnectionError("Porta seriale non aperta.")
        full_command = f"{command}\r\n".encode('ascii')
        self.ser.write(full_command)
        logging.debug(f"-> CMD: {command}")
        deadline = time.time() + (self.connection_params.get('timeout') or 2)
        while time.time() < deadline:
            line = self.ser.readline()
            if line:
                resp = line.decode('ascii', errors='ignore').strip()
                logging.debug(f"<- RESP: {resp}")
                return resp
        raise TimeoutError(f"Timeout attendendo risposta a '{command}'")

    def _send_and_check(self, command: str, expected: str = "*", retries: int = 3):
        last_err = None
        for _ in range(max(1, retries)):
            try:
                response = self.send_command(command)
                if expected in response:
                    return
                error_message = FLUKE_ERROR_CODES.get(response, f"Risposta inattesa: '{response}'")
                raise IOError(f"Comando '{command}' fallito. {error_message}")
            except Exception as e:
                last_err = e
                time.sleep(0.2)
        raise last_err

    def get_first_reading(self) -> str:
        self._send_and_check("MREAD")
        reading = None
        
        try:
            for _ in range(15):
                line = self.ser.readline().decode('ascii').strip()
                if not line:
                    continue

                # Se la risposta è un errore conosciuto, la restituiamo come risultato
                if line in FLUKE_ERROR_CODES:
                    logging.warning(f"Strumento ha riportato un codice di errore: {line}")
                    reading = line # Restituisce il codice di errore (es. '!21')
                    break

                # Altrimenti, cerca un valore numerico come prima
                if re.search(r'\d', line):
                    logging.debug(f"<- MREAD: {line}")
                    reading = line
                    break
                
                time.sleep(0.2)
        finally:
            # Questa parte viene eseguita sempre per garantire che lo strumento esca dalla modalità di lettura
            self.ser.write(b'\x1b')
            time.sleep(0.2)
            if self.ser.in_waiting > 0:
                self.ser.read(self.ser.in_waiting)

        return reading

    def extract_numeric_value(self, raw_response: str) -> str:
        if raw_response is None:
            raise ValueError("Nessuna lettura valida ricevuta dallo strumento (timeout).")
        # Regex migliorata per gestire numeri in notazione scientifica
        match = re.search(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', raw_response)
        if not match:
            raise ValueError(f"Impossibile estrarre un valore numerico dalla risposta: '{raw_response}'")
        return match.group(0)

    # --- FUNZIONI DI TEST DI ALTO LIVELLO ---
    def esegui_test_tensione_rete(self, parametro_test: str, **kwargs):
        param_map = {"Da Fase a Neutro": "L1-L2", "Da Neutro a Terra": "L2-GND", "Da Fase a Terra": "L1-GND"}
        fluke_param = param_map.get(parametro_test)
        if not fluke_param:
            raise ValueError(f"Parametro test tensione non valido: {parametro_test}")
        self._send_and_check("STD=353")
        self._send_and_check(f"MAINS={fluke_param}")
        time.sleep(0.3)
        raw_reading = self.get_first_reading()
        # Se la lettura è un codice di errore, restituiscilo direttamente
        if raw_reading and raw_reading.startswith('!'):
            return raw_reading
        return self.extract_numeric_value(raw_reading)

    def esegui_test_resistenza_terra(self, **kwargs):
        self._send_and_check("STD=353")
        self._send_and_check("ERES")
        time.sleep(0.3)
        raw_reading = self.get_first_reading()
        # Se la lettura è un codice di errore, restituiscilo direttamente
        if raw_reading and raw_reading.startswith('!'):
            return raw_reading
        return self.extract_numeric_value(raw_reading)

    def esegui_test_dispersione_diretta(self, parametro_test: str, **kwargs):
        is_reverse = "inversa" in parametro_test.lower()
        self._send_and_check("STD=353")
        time.sleep(0.3)
        self._send_and_check("DIRL")
        time.sleep(0.2)
        self._send_and_check("MODE=ACDC")
        time.sleep(0.1)
        self._send_and_check("EARTH=O")
        time.sleep(0.2)
        self._send_and_check("POL=OFF")
        time.sleep(3)
        polarity_command = "POL=R" if is_reverse else "POL=N"
        self._send_and_check(polarity_command)
        time.sleep(0.3)
        self._send_and_check("AP=ALL//")
        time.sleep(1)
        raw_reading = self.get_first_reading()
        # Se la lettura è un codice di errore, restituiscilo direttamente
        if raw_reading and raw_reading.startswith('!'):
            return raw_reading
        return self.extract_numeric_value(raw_reading)
        
    
    def esegui_test_dispersione_parti_applicate(self, parametro_test: str, pa_code: str = "ALL", **kwargs):
        is_reverse = "inversa" in parametro_test.lower()
        self._send_and_check("STD=353")
        time.sleep(0.3)
        self._send_and_check("NOMINAL=ON")
        time.sleep(0.2) 
        self._send_and_check("DMAP")
        time.sleep(0.1)
        self._send_and_check("MAP=3.5MA")
        time.sleep(0.1)
        self._send_and_check("MODE=ACDC")
        time.sleep(0.2)
        self._send_and_check("POL=OFF")
        time.sleep(3)
        polarity_command = "POL=R" if is_reverse else "POL=N"
        self._send_and_check(polarity_command)
        time.sleep(0.3)
        self._send_and_check(f"AP={pa_code}//OPEN")
        time.sleep(0.3)
        raw_reading = self.get_first_reading()
        self._send_and_check("NOMINAL=OFF")
        time.sleep(0.1)
        if self.ser.in_waiting > 0:
            self.ser.read(self.ser.in_waiting)
        # Se la lettura è un codice di errore, restituiscilo direttamente
        if raw_reading and raw_reading.startswith('!'):
            return raw_reading
        return self.extract_numeric_value(raw_reading)

    @staticmethod
    def list_available_ports():
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]
