#!/usr/bin/env python3
#a simple program to parse the serial input

import serial
import time
import datetime
import json

# serial port configuration ( 1200 7E1 )
ser = serial.Serial(
	port='/dev/ttyUSB0',
	baudrate=1200,
	parity=serial.PARITY_EVEN,
	stopbits=serial.STOPBITS_ONE,
	bytesize=serial.SEVENBITS
)

# if the serial port is not open, open it
if not ser.isOpen():
	ser.open()

def verif_checksum(data, checksum):
	data_unicode = 0
	for caractere in data:
		data_unicode += ord(caractere)
	sum_unicode = (data_unicode & 63) + 32
	return (checksum == chr(sum_unicode))


# read the serial port
while True:
	# read the serial port
	line = ser.readline()
	# decode the line
	line_str = line.decode('utf-8')

	try:
		
		[key, val, *_] = line_str.split(" ")
		# validate the line
		checksum = (line.replace('\x03\x02', ''))[-3:-2]
		if verif_checksum(f"{key} {val}", checksum):
			print("checksum ok")
			print(line)
	except Exception as e:
		print("smth wrong : " + str(e))