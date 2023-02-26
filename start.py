#!/usr/bin/env python3
# using a serial input to get the telemetry data from the linky ( french smart meter ) and send it to a InfluxDB database to be used by grafana
# log every information hold the timestamp and the data
# the data is stored in a json format
# the data is stored in a collection named "data" in a database named "linky"
# the database is hosted on a raspberry pi 3b+ with a InfluxDB server
# the raspberry pi is connected to the linky with a usb to serial converter

# this program also comunicate with an ADC+PGA I2C board to get the current of a solar panel and send it to the database
# the board is connected to the raspberry pi with the I2C bus

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
# PAPP 01070 ) // Puissance apparente soutirée
# HHPHC A , // Horaire Heures Pleines Heures Creuses ( groupe horaire )
# MOTDETAT 000000 B // état du compteur

# import the needed libraries
import serial
import time
from datetime import datetime
import requests
from influxdb import InfluxDBClient
import logging
# import the needed libraries for the ADC
import board
import busio
import adafruit_ads1x15.ads1015 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

# configure the ADC+PGA I2C board
i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS.ADS1015(i2c)
solar1 = AnalogIn(ads, ADS.P0, ADS.P1)
solar2 = AnalogIn(ads, ADS.P2, ADS.P3)


# configuration
FREQUENCY=10
DB_NAME="linky"
INT_MEASURES = ["ISOUSC", "IINST1", "IINST2", "IINST3", "IMAX1", "IMAX2", "IMAX3", "PMAX", "PAPP",]
FLOAT_MEASURES = ["BBRHCJB", "BBRHPJB", "BBRHCJW", "BBRHPJW", "BBRHCJR", "BBRHPJR"]
STRING_MEASURES = ["OPTARIF", "PTEC", "DEMAIN", "HHPHC", "MOTDETAT"]

# Connect to the database
print("Database %s connection.." % DB_NAME)
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

def modify_data(trame):
	for key, value in trame.items():
		# si la clé est DEMAIN
		if key == "DEMAIN":
			# si on est entre 20h05 et 6h
			if ((20 * 60 * 60) + (5 * 60)) < (time.time() % (24 * 3600)) < (6 * 3600):
				# si la valeur est ----
				if value == "----":
					trame[key] = "BLEU"

	# add the solar panel data

	# convert the voltage to a current
	# the voltage is between 0 and 5v
	# the clamp is a 5a/1v clamp
	# the current is between 0 and (5a/1v)*5v = 25A
	# the module is a 16 bit ADC so margin of error is 0.000015 = 0.0015% of the current so 0.15A

	current1 = (solar1.voltage)* (5/1) * 1.5
	current2 = (solar2.voltage)* (5/1) * 1.5

	# since we have a 0.15A margin of error, we need round the current to the nearest 0.15A
	# current1 = round(current1 / 0.15) * 0.15
	# current2 = round(current2 / 0.15) * 0.15

	# add the current to the trame
	trame["ISOL1"] = current1
	trame["ISOL2"] = current2

	return trame

def verif_checksum(data, checksum):
	data_unicode = 0
	for caractere in data:
		data_unicode += ord(caractere)
	sum_unicode = (data_unicode & 63) + 32
	return (checksum == chr(sum_unicode))

initser = serial.Serial(
	port='/dev/ttyUSB0',
	baudrate=1200,
	parity=serial.PARITY_EVEN,
	stopbits=serial.STOPBITS_ONE,
	bytesize=serial.SEVENBITS
)

# main loop
with initser as ser:

	logging.info("Teleinfo is reading on /dev/ttyUSB0..")

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
				elif key in STRING_MEASURES:
					trame[key] = val
				else:
					trame[key] = val
				#trame[key] = int(val) if key in INT_MESURE_KEYS else val


			if b'\x03' in line:  # si caractère de fin dans la ligne, on insère la trame dans influx
				del trame['ADCO']  # adresse du compteur : confidentiel!
				time_measure = time.time()

				# modification des données pour influxdb
				trame = modify_data(trame)

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

