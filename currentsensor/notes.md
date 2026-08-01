# DesCPS — Projektdokumentation

Design of Cyber-Physical Systems, Semester 5

Autonomes Fahrzeugsystem: LIN-Bus-Kommunikation zwischen einem Raspberry Pi (Master) und vier ATmega328P-Mikrocontrollern (Slaves, je ein Rad).

---

## Aufgetretene Probleme und Lösungen

### Problem 1: Platine — fehlerhafte Verbindung Sensor und GND

Beim Aufbau der Platine war Kondensator **C7** falsch verdrahtet: der Vorwiderstand führte **5 V direkt zu U2** (LIN-Transceiver), ohne korrekte GND-Anbindung des Sensors. Das führte zu undefiniertem Verhalten auf dem LIN-Bus.

**Lösung:** Die Verbindung wurde in KiCad korrigiert und die Platine neu bestückt. Siehe [`Plattine.png`](Plattine.png) für den korrekten Schaltplan.

---

### Problem 2: Angehobene Beinchen

Beim Entwurf der Platine wurde eine Verbindung vom Chip für die Spannungsversorgung und die LIN-Bus-Kommunikation (U2) fehlerhaft geplant.

**Lösung:** Die fehlerhafte Verbindung wurde durch Anheben des oberen linken Beinchens von U2 getrennt.

---

### Problem 3: avrdude — Versionsproblem und fehlende DLL-Dateien

`avrdude` ließ sich unter Windows nicht starten. Fehlermeldungen wiesen auf inkompatible Versionen und fehlende DLL-Dateien hin (`libhidapi-0.dll`, `libiconv2.dll`, `libintl3.dll`, `libusb0.dll`).

**Lösung:** Eine kompatible avrdude-Version mit allen zugehörigen DLLs heruntergeladen und direkt in den Projektordner gelegt (siehe `avrdude/`-Verzeichnis). Damit ist avrdude portabel und ohne Systeminstallation nutzbar.

---

### Problem 4: Pfade in allen Makefiles anpassen

Die Makefiles enthielten hartcodierte absolute Pfade (avr-gcc, avrdude, Arduino-Libraries, avr-include), die auf einer anderen Maschine nicht existierten und zu Build-Fehlern führten.

**Lösung:** Alle Makefiles (`Controller/Makefile`, `Controller/client/Makefile`, `Controller/common/Makefile` usw.) wurden auf die lokalen Installationspfade angepasst. Beispiel aus `Controller/Makefile`:

```makefile
avrdudesrc= "C:\Users\<user>\...\avrdude"
avrgccsrc=  "C:\Users\<user>\AppData\Local\Arduino15\...\avr-gcc\7.3.0-...\bin"
ardinc=     "C:\Users\<user>\AppData\Local\Arduino15\...\cores\arduino"
```

---

### Problem 5: Pin-Belegung in `main.cpp` — DDRD vs. DDRB (LEDs)

Die LEDs waren in `main.cpp` über `DDRB` (Port B) konfiguriert, obwohl sie laut Schaltplan an Port D angeschlossen waren (und umgekehrt). Die LEDs reagierten nicht oder falsch.

**Lösung:** Die Datenrichtungsregister-Zuweisungen wurden auf `DDRD` umgestellt und die zugehörigen Pin-Definitionen in `config.hpp` / `controller.hpp` entsprechend angepasst:

```cpp
// vorher falsch:  DDRB |= (1 << LED_PIN);
// nachher korrekt:
DDRD |= (1 << LED_BLUE_PIN) | (1 << LED_GREEN_PIN) | (1 << LED_RED_PIN);
```

---

### Problem 6: MINGW — richtige Version und USB-Treiber

Zum Kompilieren unter Windows wurde MinGW benötigt. Die falsche MinGW-Variante (z. B. MINGW64) führte zu Linker-Fehlern und inkompatiblen Binaries. Zusätzlich wurde der USBasp-USB-Treiber vom System nicht erkannt.

**Lösung:**
- **MSYS2 MINGW32** installiert (32-Bit-Variante, kompatibel mit avrdude und avr-gcc).
- Im Gerätemanager das USBasp-Gerät mehrfach ausgewählt und den Treiber manuell über „Treiber aktualisieren" installiert, bis es zuverlässig erkannt wurde.

---

### Problem 7: `receivebyte` / `sendbyte` — Bitshift beachten

In der LIN-Implementierung (Slave-Seite) wurden Bytes falsch ge-shiftet. Beim Senden und Empfangen stimmten die Bit-Reihenfolgen nicht überein, was zu korrumpierten Frames führte.

**Lösung:** Die Bitshift-Operationen in `sendbyte` und `receivebyte` wurden sorgfältig gegen das LIN-Protokoll geprüft und korrigiert. Insbesondere das MSB/LSB-Verhältnis und die Parity-Bits (P0, P1) des PID-Felds:

```cpp
p0 = (pid[0] ^ pid[1] ^ pid[2] ^ pid[4]) & 0x01;
p1 = ~(pid[1] ^ pid[3] ^ pid[4] ^ pid[5]) & 0x01;
```

---

### Problem 8: Adressen von Master und Slave in `addresses.hpp` korrigieren

Die LIN-PIDs (Packet Identifier) für Master und Slaves waren in `addresses.hpp` (C++) bzw. `linaddresses.py` (Python/Raspberry) falsch zugeordnet. Master und Slave sprachen aneinander vorbei, da die Quell- und Zieladressen vertauscht oder doppelt vergeben waren.

**Lösung:** Die Arrays `sources[]`, `destinations[]` und `pids[]` wurden abgeglichen und korrigiert:

```cpp
// addresses.hpp (Slave-Seite)
const uint8_t sources[]      = {master, master, master, slave0, slave0};
const uint8_t destinations[] = {slave0, slave0, slave0, master, master};
```

---

### Problem 9: `lincomm.py` (Raspberry) — `write()` immer mit nachfolgendem `read()`

Der LIN-Transceiver am Raspberry Pi spiegelt gesendete Bytes zurück auf den RX-Pin (Half-Duplex). Ohne das Auslesen dieser Echo-Bytes nach jedem `ser.write()` liefen die gesendeten Bytes in den Empfangspuffer und wurden bei der nächsten Leseoperation fälschlicherweise als Slave-Antwort interpretiert.

**Lösung:** In `lincomm.py` wird nach jedem `ser.write()` ein `ser.read(1)` aufgerufen, um das Echo zu verwerfen:

```python
def write(self, address, data):
    self.ser.write(bytes([constants.sync]))
    response = self.ser.read(1)   # Echo verwerfen
    self.ser.write(bytes([self.addparity(address)]))
    response = self.ser.read(1)   # Echo verwerfen
    for b in data:
        self.ser.write(bytes([b]))
        response = self.ser.read(1)  # Echo verwerfen
    self.ser.write(bytes([self.checksum(data)]))
    response = self.ser.read(1)   # Echo verwerfen
```

---

### Problem 10: Reihenfolge der `messagebytes` in `linaddresses.py`

Die Liste `messagebytes` in `linaddresses.py` (Raspberry-Seite) war nicht synchron mit der Reihenfolge der PIDs in `pids[]`. Dadurch wurde beim Lesen die falsche Byte-Anzahl erwartet, was zu Timeouts und Checksummenfehlern führte.

**Lösung:** `messagebytes` wurde so umsortiert, dass Index-für-Index die korrekte Byte-Länge zum jeweiligen PID passt — identisch zur Reihenfolge in der C++-Seite (`addresses.hpp`).

