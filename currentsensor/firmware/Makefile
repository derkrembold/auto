CC=avr-gcc
OBJCOPY=avr-objcopy

avrgccsrc= "C:\Users\rembo\AppData\Local\Arduino15\packages\arduino\tools\avr-gcc\7.3.0-atmel3.6.1-arduino7\bin"
makesrc= "C:\Users\rembo\Documents\make-3.81\bin"
pth= "C:\Users\rembo\OneDrxcive\Studium\sem5\DesCPS\Controller\client\src"
avrinc= "C:\Users\rembo\AppData\Local\Arduino15\packages\arduino\tools\avr-gcc\7.3.0-atmel3.6.1-arduino7\avr\include"
ardinc= "C:\Users\rembo\AppData\Local\Arduino15\packages\arduino\hardware\avr\1.8.8\cores\arduino"
geminc= "C:\Users\rembo\AppData\Local\Arduino15\packages\arduino\hardware\avr\1.8.8\variants\standard"
harinc= "C:\Users\rembo\AppData\Local\Arduino15\packages\arduino\hardware\avr\1.8.8\cores\arduino"
sofinc= "C:\Users\rembo\AppData\Local\Arduino15\packages\arduino\hardware\avr\1.8.8\libraries\SoftwareSerial\src"
eepinc= "C:\Users\rembo\AppData\Local\Arduino15\packages\arduino\hardware\avr\1.8.8\libraries\EEPROM\src"


CC=avr-gcc.exe

#CFLAGS=-Os -DF_CPU=16000000UL -mmcu=atmega328p
CFLAGS=-DF_CPU=16000000 -O3 -DNDEBUG -mmcu=atmega328p -save-temps -Wall
PORT=/dev/ttyACM0

OBJECTS=main.o

main.o: main.cpp
	${CC} $(CFLAGS) -c -I. -I$(cliinc) -I$(ardinc) -I$(geminc) -I$(harinc) -I$(sofinc) -I$(eepinc) main.cpp -o main.o


objects: $(OBJECTS)
	


clean:
	del *.o
