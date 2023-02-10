#a simple program to parse the serial input 

import serial
import time
import datetime
import json

# serial port configuration ( 1200 7N1 )
ser = serial.Serial(
    port='/dev/ttyUSB0',
    baudrate=1200,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    bytesize=serial.SEVENBITS
)

# if the serial port is not open, open it
if not ser.isOpen():
    ser.open()

# read the serial port
while True:
    # read the serial port
    line = ser.readline()
    # decode the line
    line = line.decode('utf-8')
    # remove the \r and \n
    line = line.replace('\r','').replace('\n','')
    # split the line
    line = line.split(' ')
    # if the line is not empty
    if line != ['']:
       print(line)

    