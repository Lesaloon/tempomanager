#!/usr/bin/env python3
# using a serial input to get the telemetry data from the linky ( french smart meter ) and send it to a InfluxDB database to be used by grafana
# log every information hold the timestamp and the data
# the data is stored in a json format
# the data is stored in a collection named "data" in a database named "linky"
# the database is hosted on a raspberry pi 3b+ with a InfluxDB server
# the raspberry pi is connected to the linky with a usb to serial converter

# Exemple de trame:
# ♥☻OT 00 #
# ADCO 000000000000 L // adresse du compteur
# OPTARIF BBR( S // option tarifaire
# ISOUSC 50 ; // intensité souscrite ( A )
# BBRHCJB 001964280 ;  // index heures creuses jours bleus ( / 1000 )
# BBRHPJB 002436107 A // index heures pleines jours bleus ( / 1000 )
# BBRHCJW 000681329 O // index heures creuses jours blancs ( / 1000 )
# BBRHPJW 000839029 ^ // index heures pleines jours blancs ( / 1000 )
# BBRHCJR 000921512 A // index heures creuses jours rouges ( / 1000 )
# BBRHPJR 000226574 T // index heures pleines jours rouges ( / 1000 )
# PTEC HPJR // période tarifaire en cours (Heures Pleines Jours Rouges)
# DEMAIN ---- " // couleur du lendemain
# IINST1 000 H // intensité instantanée phase 1
# IINST2 002 K // intensité instantanée phase 2
# IINST3 002 L // intensité instantanée phase 3
# IMAX1 060 6 // intensité maximale phase 1
# IMAX2 060 7 // intensité maximale phase 2
# IMAX3 060 8 // intensité maximale phase 3
# PMAX 14054 4 // puissance maximale atteinte sur la période de relevé ( 24h )
# PAPP 01070 ) // puissance apparente soutirée
# HHPHC A , // Horaire Heures Pleines Heures Creuses ( groupe horaire )
# MOTDETAT 000000 B // état du compteur


# import the needed libraries
import serial
import time
import datetime
import json
import requests
from influxdb import InfluxDBClient
import logging




# configuration
FREQUENCY=10
DB_NAME="linky"
INT_MEASURES = ["ISOUSC", "IINST1", "IINST2", "IINST3", "IMAX1", "IMAX2", "IMAX3", "PMAX", "PAPP",]
FLOAT_MEASURES = ["BBRHCJB", "BBRHPJB", "BBRHCJW", "BBRHPJW", "BBRHCJR", "BBRHPJR"]

# serial port configuration ( 9600 7E1 )
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

# Connect to the database
client = InfluxDBClient('localhost', 8086)
connected = False
while not connected:
	try:
		logging.info("Database %s exists?" % DB_NAME)
		# if the database does not exist
		if not {'name': DB_NAME} in client.get_list_database():
			# create the database
			logging.info("Database %s creation.." % DB_NAME)
			client.create_database(DB_NAME)
			logging.info("Database %s created!" % DB_NAME)
		# switch to the database
		client.switch_database(DB_NAME)
		logging.info("Connected to %s!" % DB_NAME)
	# if the database is not reachable
	except requests.exceptions.ConnectionError:
		logging.info('InfluxDB is not reachable. Waiting 5 seconds to retry.')
		time.sleep(5)
	else:
		connected = True

def add_measures(measures, time_measure):
	points = []
	for measure, value in measures.items():
		point = {
			"measurement": measure,
			"tags": {
				# identification de la sonde et du compteur
				"host": "raspberry",
				"region": "linky"
			},
			"time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
			"fields": {
				"value": value
			}
		}
		points.append(point)

	client.write_points(points)


def verif_checksum(data, checksum):
	data_unicode = 0
	for caractere in data:
		data_unicode += ord(caractere)
	sum_unicode = (data_unicode & 63) + 32
	return (checksum == chr(sum_unicode))


# main loop
with serial.Serial(port='/dev/ttyS0', baudrate=1200, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, bytesize=serial.SEVENBITS, timeout=1) as ser:

	logging.info("Teleinfo is reading on /dev/ttyS0..")

	trame = dict()

	# boucle pour partir sur un début de trame
	line = ser.readline()
	while b'\x02' not in line:  # recherche du caractère de début de trame
		line = ser.readline()

	# lecture de la première ligne de la première trame
	line = ser.readline()

	while True:
		line_str = line.decode("utf-8")
		logging.debug(line)

		try:
			# separation sur espace /!\ attention le caractere de controle 0x32 est un espace aussi
			[key, val, *_] = line_str.split(" ")

			# supprimer les retours charriot et saut de ligne puis selectionne le caractere
			# de controle en partant de la fin
			checksum = (line_str.replace('\x03\x02', ''))[-3:-2]

			if verif_checksum(f"{key} {val}", checksum):
				# creation du champ pour la trame en cours avec cast des valeurs de mesure en "integer"
				if key in INT_MEASURES:
					trame[key] = int(val)
				elif key in FLOAT_MEASURES:
					trame[key] = float(val) / 1000
				else:
					trame[key] = val
				#trame[key] = int(val) if key in INT_MESURE_KEYS else val

			if b'\x03' in line:  # si caractère de fin dans la ligne, on insère la trame dans influx
				del trame['ADCO']  # adresse du compteur : confidentiel!
				time_measure = time.time()

				# insertion dans influxdb
				add_measures(trame, time_measure)

				# ajout timestamp pour debugger
				trame["timestamp"] = int(time_measure)
				logging.debug(trame)

				trame = dict()  # on repart sur une nouvelle trame
		except Exception as e:
			logging.error("Exception : %s" % e, exc_info=True)
			logging.error("%s %s" % (key, val))
		line = ser.readline()


