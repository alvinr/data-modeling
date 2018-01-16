from redis import StrictRedis, WatchError
import os
import time
import random
import string
import json
import math

redis = StrictRedis(host=os.environ.get("REDIS_HOST", "localhost"), 
                    port=os.environ.get("REDIS_PORT", 6379),
                    db=0)
redis.flushall()


def increment_char(c):
	return chr(ord(c) + 1) if c != 'Z' else 'A'

def increment_str(s):
	lpart = s.rstrip('Z')
	num_replacements = len(s) - len(lpart)
	new_s = lpart[:-1] + increment_char(lpart[-1]) if lpart else 'A'
	new_s += 'A' * num_replacements
	return new_s

def create_seat_map(event_name, rows, seats_per_row):
	row_name = "A"
	for i in range(rows):
		filled_seat_map = bin(int(math.pow(2,seats_per_row))-1)
		redis.set("events:" + event_name + ":" + row_name, filled_seat_map)
		row_name = increment_str(row_name)

def print_seat_map(event_name):
	rows = redis.keys("events:" + event_name + ":*")
	for row in rows:
		seat_map = int(redis.get(row),2)
		print("Row {}:").format(row),
		for i in range(seat_map.bit_length()):
			if ((i % 10 ) == 0):
				print "|",
			print (seat_map >> i) & 1,
		print "|"

# Part One - Create the event map
event = "Judo"
create_seat_map(event, 2, 20)
print_seat_map(event)


def check_availbale(seat_map, seats_required, first_seat=-1):
	blocks = []
	if ( first_seat != -1 ):
		end_seat = first_seat + seats_required -1
	else:
		end_seat = seat_map.bit_length()
	required_block = int(math.pow(2,seats_required))-1
	for i in range(1, end_seat):
		if ( (seat_map & required_block) == required_block ):
			blocks.append( {'first_seat': i, 'last_seat': i + seats_required -1} )
		required_block = required_block << 1
	return blocks

def find_seat_selection(event_name, seats_required):
	# Get all the seat rows
	blocks = []
	rows = redis.keys("events:" + event_name + ":*")
	for row in rows:
		seat_map = int(redis.get(row),2)
		row_blocks = check_availbale(seat_map, seats_required)
		if (len(row_blocks) > 0):
			blocks.append( {'row': row, 'blocks': row_blocks } )
	return blocks

def print_availbale_blocks(blocks):
	for block in blocks:
		current_block = block['blocks']
		for i in range(len(current_block)):
			print " Row: {}, Start {}, End {}".format(block['row'],current_block[i]['first_seat'], current_block[i]['last_seat'],)

available_blocks = find_seat_selection(event, 2)
print_availbale_blocks(available_blocks)

# Part Two - reserve seats

def set_seat_map(event_name, row, map):
	redis.set("events:" + event_name + ":" + row, map)

def reservation(event_name, row, first_seat, last_seat):
	reserved = False
	try:
		redis.watch("events:" + event_name + ":" + row)
		p = redis.pipeline()
		seat_map = int(redis.get("events:" + event_name + ":" + row),2)
		block = check_availbale(seat_map, last_seat - first_seat + 1, first_seat)
		if ( len(block) > 0 ):
			for i in range(first_seat, last_seat+1):
				seat_map = seat_map - int(math.pow(2,i-1))
			p.set("events:" + event_name + ":" + row, bin(seat_map))
			p.execute()
			reserved = True
	except WatchError:
		print "Write Conflict: {}".format("events:" + event_name + ":" + row)
	finally:
		p.reset()
	return reserved

event="Fencing"
create_seat_map(event, 1, 10)
# Seat 4 (the 8th bit) is already sold. We calc this as (2^(seats)-1) - bit_number_of_seat, e.g. 1023 - 8
set_seat_map(event, "A", bin(1023-8))
print_seat_map(event)
blocks = find_seat_selection(event, 2)
print_availbale_blocks(blocks)
# Just choose the first found
made_reservation = reservation(event, "A", blocks[0]['blocks'][0]['first_seat'], blocks[0]['blocks'][0]['last_seat'])
print "Made restervation? {}".format(made_reservation)
print_seat_map(event)

blocks = find_seat_selection(event, 5)
print_availbale_blocks(blocks)
# Just choose the first found
made_reservation = reservation(event, "A", blocks[0]['blocks'][0]['first_seat'], blocks[0]['blocks'][0]['last_seat'])
print "Made restervation? {}".format(made_reservation)
print_seat_map(event)



