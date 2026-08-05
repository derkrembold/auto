# STM32 Firmware Notes

Reference material for the existing BLDC control firmware, consolidated
from working notes (originally German, kept as written). See
`STM32/CLAUDE.md` for the summarized version of this; this file is the
detail behind it.

## Mikrocontroller

Der Mikrocontroller, den ich verwende ist: **STM32H743VGT6**

Die GPIOs für die Hallsensoren sind:
- PC0
- PC1
- PC2

Die GPIOs für die MOSFETS sind:
- PE8
- PE9
- PE10
- PE11
- PE12
- PE13

## Betriebsbedingungen

Der Motor läuft aktuell auf 24V.
Der Trafo hat eine Strombegrenzung.
Ab einer bestimmten Steuerungswert scheint der Motor in eine Sättigung zu
laufen, vielleicht wegen Strombegrenzung.

## Drehzahlen (gemessen)

Unten sind die gemessenen Drehzahlen. Es wurde ein Steuerungswert
eingegeben und dann die Drehzahl gemessen. Gemessen wurde sie durch
Zählen von Interrupts bei den GPIOs PC0, PC1 und PC2. Die drei
Hallsensoren liegen an diesen GPIOs an.

Die Drehzahl habe ich ermittelt durch:
`rpm = (60sec/min * hallCounter) / (24steps/Umdrehung * Taktrate)`

`hallCounter` ist der Wert, der durch die Interruptroutine hoch- oder
runtergezählt wird, je nachdem ob CW oder CCW. Eine Umdrehung ist 24
steps. Taktrate kann ich einstellen, z.B. 0.05s, 0.1s, 0.2s.

**Vorsicht: diese Werte mit Skepsis behandeln.** Unklar, ob sie noch
aktuell sind — möglicherweise veraltet (andere Firmware-Version,
andere Betriebsspannung o.ä. zum Zeitpunkt der Messung). Nicht
ungeprüft als aktuelle Referenz verwenden.

| Steuerwert | Drehzahl in U/min |
|-----------:|-------------------:|
| -550 | -2800 |
| -500 | -2800 |
| -450 | -2775 |
| -400 | -2700 |
| -350 | -2525 |
| -300 | -2275 |
| -250 | -1800 |
| -200 | -1275 |
| -150 | -625 |
| 150 | 625 |
| 200 | 1325 |
| 250 | 1800 |
| 300 | 2250 |
| 350 | 2500 |
| 400 | 2700 |
| 450 | 2750 |
| 500 | 2800 |
| 550 | 2825 |

## driveState()

Die Funktion `driveState()`. Parameter sind `speed` (Geschwindigkeit) und
`st` (Zustand).

Die Funktionsweise ist:

1. Alle MOSFETs aus.
2. Falls `speed` ist 0, wird die Funktion abgebrochen.
3. Es wird eine Variable `chargetime` auf 10 Mikrosekunden gesetzt.
4. Es wird die Variable `rate` auf 1275 gesetzt.
5. Der Parameter `speed` wird mit 5 multipliziert und ergibt die Variable
   `speedrate`. 5*256 ergibt 1275! Also 255 ist max. speed.
6. Abhängig vom Parameter `st` werden MOSFETs geschaltet, und zwar für
   die Länge `chargetime`, um den Bootstrap-Kondensator aufzuladen.
7. Abhängig vom Parameter `st` werden MOSFETs geschaltet, um den BLDC mit
   seinen drei Phasen anzusteuern. Die Variable `speedrate` gibt die
   Dauer für das Durchschalten der MOSFETs an — ist `speedrate` groß,
   schalten die MOSFETs lange durch.
8. Dann werden alle MOSFETs ausgemacht.
9. Dann wird noch gewartet, bis die 1275 Mikrosekunden durch sind, also:
   `1275 Mikrosekunden - 5*speed`.

Insgesamt ist die Rate: 1275 Mikrosekunden + 10 Mikrosekunden.

## Kommutierungszustände (Hall → nächster Zustand)

Oszillator-Zuordnung:
- Probe Farbe gelb: PC0; Position Platine oben
- Probe Farbe rot: PC1; Position Platine mitte
- Probe Farbe blau: PC2; Position Platine unten

**CW:**

| Current state | PC0/gelb/first | PC1/rot/second | PC2/blau/third | Function Call for next state |
|---|---|---|---|---|
| state4 | 1 | 0 | 0 | `driveState(speed, 5)` |
| state5 | 1 | 0 | 1 | `driveState(speed, 0)` |
| state0 | 0 | 0 | 1 | `driveState(speed, 1)` |
| state1 | 0 | 1 | 1 | `driveState(speed, 2)` |
| state2 | 0 | 1 | 0 | `driveState(speed, 3)` |
| state3 | 1 | 1 | 0 | `driveState(speed, 4)` |

**CCW:**

| Current state | PC0/gelb/first | PC1/rot/second | PC2/blau/third | Function Call for next state |
|---|---|---|---|---|
| state2 | 0 | 1 | 0 | `driveState(speed, 4)` |
| state1 | 0 | 1 | 1 | `driveState(speed, 3)` |
| state0 | 0 | 0 | 1 | `driveState(speed, 2)` |
| state5 | 1 | 0 | 1 | `driveState(speed, 1)` |
| state4 | 1 | 0 | 0 | `driveState(speed, 0)` |
| state3 | 1 | 1 | 0 | `driveState(speed, 5)` |

## Hauptschleife

Das aktuelle Programm funktioniert so:

Es gibt eine Endless Loop. Dort wird immer die Funktion `driveStep()`
aufgerufen. `driveStep()` hat die Parameter `speedglobal` und
`dirglobal`. `speedglobal` ist die Geschwindigkeit, `dirglobal` ist die
Richtung.

In `driveStep()` werden erst die Hall-Sensoren gelesen. Es sind drei
Sensoren, dies ergibt sechs Positionszustände (nicht drei, wegen Gray
Code). Abhängig von der Richtung (`dirglobal`) und dem Zustand werden die
Parameter von `driveState()` gesetzt — `speed` und `st` (der nächste
Zustand). Abhängig vom nächsten Zustand werden die 6 MOSFETs angesteuert.

In `driveState()` ist ein Timer, der abhängig von `speed` gesetzt wird:
ist `speed` groß, werden die MOSFETs länger durchgeschaltet als wenn
`speed` klein ist. `driveState()` wartet immer gleich lang, definiert
durch die Variable `rate` (aktuell 1275 Mikrosekunden). Der Parameter
`speed` bestimmt lediglich, wie lange die MOSFETs durchgeschaltet sind.

## PI-Regler (picontrol.c)

```c
int16_t picontrol(int16_t setpoint, int16_t processvalue)
{

    if(setpoint == 0)
    {
        integral = 0.0f;
        return 0;
    }
    // Anlauflogik
    /*if(abs(processvalue) < 200)
    {
        int16_t boost = 200 - (abs(processvalue));
        return (setpoint > 0) ? boost : -boost;
    }
    if(setpoint > 0 && setpoint < 400)
        setpoint = 400;
    else if(setpoint < 0 && setpoint > -400)
        setpoint = -400;
*/
    float error = (float)(setpoint - processvalue);
    float newintegral = integral + error;

    float controlvariable = KP * error + KI * DT * integral;

    // Anti-Windup - Begrenzen
    if(controlvariable > CONTROLLIMIT)
    {
    	controlvariable = CONTROLLIMIT;
    	if (error < 0) {
    		integral = newintegral;
    	}
    } else if(controlvariable < -CONTROLLIMIT)
    {
    	controlvariable = -CONTROLLIMIT;
    	if (error > 0) {
    		integral = newintegral;
    	}
    } else {
		integral = newintegral;
    }
    /*
    if(abs(processvalue) < 60)  // Motor steht quasi
    {
    	if(controlvariable > 0 && controlvariable < 100)
    		controlvariable = 100;
    	else if(controlvariable < 0 && controlvariable > -100)
    		controlvariable = -100;
    }*/
    return (int16_t)controlvariable;
}
```

`KP`, `KI`, `DT`, `CONTROLLIMIT` are referenced but not defined in this
snippet — presumably defined elsewhere in the firmware source.

## Fehlerliste

**Issue #1**

Symptom: Der Motor erbrachte sichtlich weniger Drehzahl und Leistung.
Beim Start fing er oft nicht an zu drehen. Veränderte ich die Position
der Achse, drehte er sich.

Problem: Es gibt einen Shuntwiderstand bei einem der MOSFET-Paare, um
Strom zu messen. Dieser hatte nicht mehr den ursprünglichen Widerstand,
sondern 600Ω — zu viel für einen Shunt. Er ist wohl halb durchgebrannt.
Der Shunt war zu klein dimensioniert.

Lösung: Shunt rausgelötet und eine Kupferbrücke rein. **Strommessung ist
nun nicht mehr möglich.**

**Issue #2 (2026-08-05)**

Symptom: Firmware-Test für PB14/PB15 (Jumper-Erkennung über
`Conn_02x05_Top_Bottom`, siehe `STM32/CLAUDE.md`) reagierte nicht auf
den Jumper — LEDs blieben unbeeinflusst vom Pin-Zustand. Firmware-Logik
und KiCad-Schaltplan (PB14→J1 Pin 7, PB15→J1 Pin 5, beide direkt ohne
weitere Bauteile) waren beide nachweislich korrekt; das Board lief
ansonsten normal (LIN/Hall-Antworten funktionierten).

Problem: Zwei kalte Lötstellen am Connector (`J1`).

Lösung: Nachgelötet. Jumper-Erkennung funktioniert seitdem wie erwartet.

## Messwerte (Oszilloskop)

Tabelle mit Messwerten: Es wird mit dem Oszilloskop der zeitliche Abstand
zwischen 6 Zustandswechseln gemessen.

**Vorsicht: diese Werte mit Skepsis behandeln.** Unklar, ob sie noch
aktuell sind — möglicherweise veraltet. Nicht ungeprüft als aktuelle
Referenz verwenden.

| Steuerungswert | Oszilloskop |
|---:|---:|
| 45 | 11,0 ms |
| 50 | 10,5 ms |
| 55 | 9,4 ms |
| 60 | 8,9 ms |
| 65 | 7,9 ms |
| 70 | 7,5 ms |
| 75 | 7,3 ms |
| 80 | 7,0 ms |

## STM32CubeIDE Projektstruktur

Auflistung der Ordnerpfade des STM32CubeIDE-Projekts (project files named
`demoboard`/`BringUpBoard`). Volumeseriennummer: B256-9736.

```
C:.
|   .cproject
|   .mxproject
|   .project
|   demoboard.ioc
|   demoboard.launch
|   STM32H743VGTX_FLASH.ld
|   STM32H743VGTX_RAM.ld
|
+---.settings
|       language.settings.xml
|       org.eclipse.core.resources.prefs
|       stm32cubeide.project.prefs
|
+---Core
|   +---Inc
|   |       addresses.h
|   |       errors.h
|   |       main.h
|   |       stm32h7xx_hal_conf.h
|   |       stm32h7xx_it.h
|   |
|   +---Src
|   |       main.c
|   |       stm32h7xx_hal_msp.c
|   |       stm32h7xx_it.c
|   |       syscalls.c
|   |       sysmem.c
|   |       system_stm32h7xx.c
|   |
|   \---Startup
|           startup_stm32h743vgtx.s
|
+---Debug
|   |   BringUpBoard.elf
|   |   BringUpBoard.list
|   |   BringUpBoard.map
|   |   demoboard.elf
|   |   demoboard.list
|   |   demoboard.map
|   |   makefile
|   |   objects.list
|   |   objects.mk
|   |   sources.mk
|   |
|   +---Core
|   |   +---Src
|   |   |       lin.cyclo, lin.d, lin.o, lin.su
|   |   |       main.cyclo, main.d, main.o, main.su
|   |   |       stm32h7xx_hal_msp.*, stm32h7xx_it.*
|   |   |       syscalls.*, sysmem.*, system_stm32h7xx.*
|   |   |       subdir.mk
|   |   |
|   |   \---Startup
|   |           startup_stm32h743vgtx.d, .o, subdir.mk
|   |
|   \---Drivers
|       \---STM32H7xx_HAL_Driver
|           \---Src
|                   stm32h7xx_hal*.cyclo/.d/.o/.su (adc, adc_ex, cortex,
|                   dma, dma_ex, exti, flash, flash_ex, gpio, hsem, i2c,
|                   i2c_ex, mdma, pwr, pwr_ex, rcc, rcc_ex, tim, tim_ex,
|                   uart, uart_ex)
|
\---Drivers
    +---CMSIS
    |   +---Device/ST/STM32H7xx/Include  (stm32h743xx.h, stm32h7xx.h, ...)
    |   \---Include                       (CMSIS core headers)
    \---STM32H7xx_HAL_Driver
        +---Inc     (stm32h7xx_hal*.h, stm32h7xx_ll*.h, Legacy/)
        \---Src     (stm32h7xx_hal*.c)
```

Note: build artifacts under `Debug/Core/Src/` reference `lin.cyclo`/
`lin.o` (compiled `lin` source), even though a `lin.c`/`lin.cpp` source
file isn't listed under `Core/Src` above — it may have been renamed,
moved, or the listing predates/postdates that file's presence. Worth
checking directly against the live project rather than assuming from
this snapshot.
