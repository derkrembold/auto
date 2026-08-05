CC=avr-gcc
OBJCOPY=avr-objcopy
avrdudesrc=C:\Users\rembo\Documents\Avrdude\avrdude-v7.0-windows-x64
avrdudecnf=C:\Users\rembo\Documents\Avrdude\avrdude-v7.0-windows-x64
avrgccsrc=C:\Users\rembo\AppData\Local\Arduino15\pAckages\arduino\tools\avr-gcc\7.3.0-atmel3.6.1-arduino7\bin
makesrc=C:\Users\rembo\Documents\Make\make-3.81-bin\bin
pth=C:\Users\rembo\Documents\ATMEGA328\Controller\client\src
avrinc=C:\Users\rembo\AppData\Local\Arduino15\packages\arduino\tools\avr-gcc\7.3.0-atmel3.6.1-arduino7\avr\include
ardinc=C:\Users\rembo\AppData\Local\Arduino15\packages\arduino\hardware\avr\1.8.8\cores\arduino
geminc=C:\Users\rembo\AppData\Local\Arduino15\packages\arduino\hardware\avr\1.8.8\variants\standard
harinc=C:\Users\rembo\AppData\Local\Arduino15\packages\arduino\hardware\avr\1.8.8\cores\arduino
sofinc=C:\Users\rembo\AppData\Local\Arduino15\packages\arduino\hardware\avr\1.8.8\libraries\SoftwareSerial\src



CC=avr-gcc.exe
CXX=avr-g++.exe

#CORE_OBJECTS=cores\arduino\wiring_analog.o cores\arduino\wiring_digital.o cores\arduino\Print.o cores\arduino\abi.o cores\arduino\HardwareSerial.o cores\arduino\HardwareSerial0.o cores\arduino\HardwareSerial1.o cores\arduino\HardwareSerial2.o cores\arduino\HardwareSerial3.o

CUR_OBJECTS= firmware\main.o #$(CORE_OBJECTS)

CFLAGS=-DF_CPU=16000000 -O3 -DNDEBUG -mmcu=atmega328p -save-temps -Wall

objects:
	cd firmware && make -f Makefile objects


current.elf: objects
	${CC} $(CFLAGS) -o current.elf $(CUR_OBJECTS)

current.hex: current.elf
	${OBJCOPY} -O ihex -R .eeprom current.elf current.hex


all: current.hex

clean:
	cd firmware && make -f Makefile clean
	del *.hex
	del *.elf
