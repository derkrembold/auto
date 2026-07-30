import serial
import os
import time
import sys
import RPi.GPIO as GPIO
from linaddresses import constants
import numpy as np
import pygame
import subprocess
import struct


MAXSET = 160
MINSET = -160

class Lin:

    def __init__(self):
        SLP_PIN = 23  # GPIO16
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(SLP_PIN, GPIO.OUT)
        GPIO.output(SLP_PIN, GPIO.HIGH)  # LIN-Transceiver aktivieren
        
        self.ser = serial.Serial(
            port='/dev/ttyS0',  # Standard UART des Raspberry Pi
            baudrate=19200,       # LIN-Bus Baudrate
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            timeout=2 # Timeout für Empfang erhoeht
        )
        
        
    def checksum(self, data):
        check = 0
        for abyte in data:
            check += abyte
            if check > 0xFF:
                check -=  0xFF
        check = (~check) & 0xFF
        return check
    


    def addparity(self, pid):
        
        temp = pid & 0x3F;
        p0 = ((pid & 0x01) + ((pid >> 1) & 0x01) + ((pid >> 2) & 0x01) + ((pid >> 4) & 0x01)) & 0x01;
        p1 = (~(((pid>>1) & 0x01) + ((pid >> 3) & 0x01) + ((pid >> 4) & 0x01) + ((pid >> 5) & 0x01))) & 0x01;
        
        temp = (p0 << 6) | temp;
        temp = (p1 << 7) | temp;
        return temp;


    def write(self, address, data):

        if address not in constants.pids:
            print("pid not known")
            return -1
        index = constants.pids.index(address)
        mbytes = constants.messagebytes[index]
        if len(data) != mbytes:
            print("number of bytes wrong")
            return -2
        
        if constants.sources[index] != constants.master:
            print("you must be master to write")
            return -3
        
        self.ser.write(bytes([constants.sync]))
        response = self.ser.read(1)
        #print(f"Raw: {response.hex()}")
        self.ser.write(bytes([self.addparity(address)]))
        response = self.ser.read(1)
        #print(f"Raw: {response.hex()}")
        
        for b in data:
            self.ser.write(bytes([b]))
            response = self.ser.read(1)
            #print(f"Raw: {response.hex()}")

        
        self.ser.write(bytes([self.checksum(data)]))
        response = self.ser.read(1)
        #print(f"Raw: {response.hex()}")

        return 0


    def read(self, address):

        #print("address: ", address)
        #print("constants: ", constants.pids)
        
        if address not in constants.pids:
            print("pid not known")
            return -1, []

        index = constants.pids.index(address)
        mbytes = constants.messagebytes[index]

        if constants.sources[index] == constants.master:
            print("you must be client to write")
            return -2, []
        
        self.ser.write(bytes([constants.sync]))
        response = self.ser.read(1)
        #print(f"Raw: {response.hex()}")
        self.ser.write(bytes([self.addparity(address)]))
        response = self.ser.read(1)
        #print(f"Raw: {response.hex()}")

        data = []
        for b in range(0,mbytes):
            response = self.ser.read(1)
            #print(type(response[0]))
            data.append(response[0])
            #print(f"Raw: {response.hex()}")

        response = self.ser.read(1)
        #print(f"Raw: {response.hex()}")
        if response[0] != self.checksum(data):
            print("checksum not right")
            return -3, []
            
        return 0, data
    
    def close(self):
        self.ser.close()
        GPIO.cleanup()


def addparity(pid):
    
    temp = pid & 0x3F;
    p0 = ((pid & 0x01) + ((pid >> 1) & 0x01) + ((pid >> 2) & 0x01) + ((pid >> 4) & 0x01)) & 0x01;
    p1 = (~(((pid>>1) & 0x01) + ((pid >> 3) & 0x01) + ((pid >> 4) & 0x01) + ((pid >> 5) & 0x01))) & 0x01;
    
    temp = (p0 << 6) | temp;
    temp = (p1 << 7) | temp;
    return temp;


def checksum(data):
    check = 0
    for abyte in data:
        check += abyte
        if check > 0xFF:
            check -=  0xFF
    check = (~check) & 0xFF
    return check



"""
def main():

    dw = {"SLV0": constants.cntlslv0, "SLV1": constants.cntlslv1, "SLV2": constants.cntlslv2 ,"SLV3": constants.cntlslv3}
    data = [0xaa, 0xcd]

    lin = Lin()
    ret = 0

    try:
        while True:
            #print("1")
            ret = lin.write(dw["SLV1"], data)
            if ret < 0:
                print(f"something wrong with run: {ret}")
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        lin.close()
        print("done")

        
    return
"""

def getindex(pid):
    for i, apid in enumerate(constants.pids):
        if apid == pid:
            return i
    return -1

def main():


    SLP_PIN = 23  # GPIO16
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(SLP_PIN, GPIO.OUT)
    GPIO.output(SLP_PIN, GPIO.HIGH)  # LIN-Transceiver aktivieren
        
    ser = serial.Serial(
        port='/dev/ttyS0',  # Standard UART des Raspberry Pi
        baudrate=19200,       # LIN-Bus Baudrate
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.EIGHTBITS,
        timeout=2 # Timeout für Empfang erhoeht
    )


    try:

        if sys.argv[1] == "chain":
                for i in range(0,7*12):
                    ser.write(bytes([0x55, addparity(constants.cntlslv1)]))
                    data = [i%7]
                    ser.write(bytes(data))
                    ser.write(bytes([checksum(data)]))
                    time.sleep(0.05)

        
        if sys.argv[1] == "on":
            ser.write(bytes([0x55, addparity(constants.cntlslv0)]))
            data = [0x01, 0xdb]
            ser.write(bytes(data))
            ser.write(bytes([checksum(data)]))

        
        if sys.argv[1] == "off":
            ser.write(bytes([0x55, addparity(constants.cntlslv0)]))
            data = [0xcd, 0x0c]
            ser.write(bytes(data))
            ser.write(bytes([checksum(data)]))

        if sys.argv[1] == "step":
            print(f"st={int(sys.argv[2])}")

            wert = int(sys.argv[2])
            if wert > 32767:
                wert = 32767
            if wert < -32768:
                wert = -32768
            daten = struct.pack('>h', wert)
            print(f"{wert} -> Bytes {daten.hex()}")

            ser.write(bytes([0x55, addparity(constants.cntlslv1)]))
            ser.write(bytes(daten))
            ser.write(bytes([checksum(daten)]))

        if sys.argv[1] == "run":
            print(f"step={int(sys.argv[2])}")

            wert = int(sys.argv[2])
            if wert > 32767:
                wert = 32767
            if wert < -32768:
                wert = -32768
            daten = struct.pack('>h', wert)
            print(f"{wert} -> Bytes {daten.hex()}")

            
            #for i in range(0,20):
            ser.write(bytes([0x55, addparity(constants.cntlslv3)]))
            #data = [int(sys.argv[2]), int(sys.argv[3])]
            #ser.write(bytes(data))
            ser.write(daten)
            #ser.write(bytes([checksum(data)]))
            ser.write(bytes([checksum(list(daten))]))
            time.sleep(0.03)
            

        if sys.argv[1] == "mosfet":
            print(f"AL={sys.argv[2]}, AH={sys.argv[3]}, BL={sys.argv[4]}, BH={sys.argv[5]}, CL={sys.argv[6]}, CH={sys.argv[7]}")
            ser.write(bytes([0x55, addparity(constants.cntlslv2)]))
            data = [int(sys.argv[2]), int(sys.argv[3]),
                    int(sys.argv[4]), int(sys.argv[5]),
                    int(sys.argv[6]), int(sys.argv[7])]

            if data.count(1) > 1:
                raise Exception("Data has more than one element with 1")
            if not set(data).issubset({0, 1}):
                raise Exception("Data contains other than zero or one")
            print(data)
            ser.write(bytes(data))
            ser.write(bytes([checksum(data)]))


        if sys.argv[1] == "hal":
            address = constants.stslv0
            ser.write(bytes([0x55]))
            response = ser.read(1)
            ser.write(bytes([addparity(address)]))
            response = ser.read(1)

            index = getindex(address)
            print("index: ", index)
        
            data = []
            for i in range(0,constants.messagebytes[index]):
                response = ser.read(1)
                print(hex(response[0]))
                #print(type(response[0]))
                data.append(response[0])
                #print(f"Raw: {response.hex()}")

            response = ser.read(1)
            print(f"Raw: {response.hex()}")
            if response[0] != checksum(data):
                print("checksum not right")
            
        if sys.argv[1] == "rpm":
            address = constants.stslv2
            ser.write(bytes([0x55]))
            response = ser.read(1)
            ser.write(bytes([addparity(address)]))
            response = ser.read(1)
        
            index = getindex(address)
            #print("index: ", index)
        
            data = []
            for i in range(0,constants.messagebytes[index]):
                response = ser.read(1)
                #print("Raw: ", hex(response[0]))
                data.append(response[0])

            response = ser.read(1)
            #print(f"Raw: {response.hex()}")
            if response[0] != checksum(data):
                print("checksum not right")

            print(f"Hex Value: {hex(data[0]+256*data[1])}")
            uval16 = np.uint16(data[0]+256*data[1])
            print(f"Value: {uval16.astype(np.int16)}")


        if sys.argv[1] == "temp":
            address = constants.stslv1
            ser.write(bytes([0x55]))
            response = ser.read(1)
            ser.write(bytes([addparity(address)]))
            response = ser.read(1)
        
            index = getindex(address)
            #print("index: ", index)
        
            data = []
            for i in range(0,constants.messagebytes[index]):
                response = ser.read(1)
                #print("Raw: ", hex(response[0]))
                data.append(response[0])

            response = ser.read(1)
            #print(f"Raw: {response.hex()}")
            if response[0] != checksum(data):
                print("checksum not right")

            print(f"Value: {hex(data[0]+256*data[1])}")
        
        time.sleep(0.2)
            
    except Exception as e:
        print(f"Some sort of error: {str(e)}")

    ser.close()
    GPIO.cleanup()
    return

def chain():

    SLP_PIN = 23  # GPIO16
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(SLP_PIN, GPIO.OUT)
    GPIO.output(SLP_PIN, GPIO.HIGH)  # LIN-Transceiver aktivieren
    
    ser = serial.Serial(
        port='/dev/ttyS0',  # Standard UART des Raspberry Pi
        baudrate=19200,       # LIN-Bus Baudrate
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.EIGHTBITS,
        timeout=2 # Timeout für Empfang erhoeht
    )


        
    ser.close()
    GPIO.cleanup()    
    return


def run():
    pygame.init()    
    pygame.joystick.init()


    SLP_PIN = 23  # GPIO16
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(SLP_PIN, GPIO.OUT)
    GPIO.output(SLP_PIN, GPIO.HIGH)  # LIN-Transceiver aktivieren
        
    ser = serial.Serial(
        port='/dev/ttyS0',  # Standard UART des Raspberry Pi
        baudrate=19200,       # LIN-Bus Baudrate
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.EIGHTBITS,
        timeout=2 # Timeout für Empfang erhoeht
    )

    
    if pygame.joystick.get_count() == 0:
        print("Kein Joystick gefunden!")
    else:
        
        joystick = pygame.joystick.Joystick(0)
        joystick.init()
        
        print(f"Joystick Name: {joystick.get_name()}")
        print(f"Anzahl Tasten: {joystick.get_numbuttons()}")
        
        try:
            num = joystick.get_numaxes()
            print(num)
            allaxis = [0 for i in range(num)]
            if num != 6:
                print("\nCould not read num of axis")
                raise ValueError("Cound not read num of axis")

            
            while True:
                
                pygame.event.pump()
                
                for i in range(joystick.get_numaxes()):
                    allaxis[i] = joystick.get_axis(i)
                    #print(f"{allaxis[i]}")
                    
                ax = int(allaxis[4]*2500)

                wert = int(ax)
                if wert > 3000:
                    wert = 3000
                if wert < -3000:
                    wert = -3000
                if abs(wert) < 500:
                    wert = 0
                daten = struct.pack('>h', wert)
                print(f"{wert} -> Bytes {daten.hex()}")

                
                    
                print(f"wert={wert}, daten[0]={daten[0]}, daten[1]={daten[1]}")
                #for i in range(0,20):
                ser.write(bytes([0x55, addparity(constants.cntlslv3)]))
                ser.write(daten)
                ser.write(bytes([checksum(list(daten))]))
                time.sleep(0.5)
                    
        except KeyboardInterrupt:
            # Aufräumen bei Abbruch
            print("\nKeyboard Interrupt caught")

        except ValueError:
            print("\nValueError caught")


        ser.close()
        GPIO.cleanup()    
        pygame.quit()
        

if __name__ == "__main__":

    run()
    #chain()
    #main()

    
