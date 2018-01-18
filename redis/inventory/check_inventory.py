from redis import StrictRedis, WatchError
import os
import string
import json
import math
import random
import struct

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

def create_event(event_name, rows, seats_per_row):
	redis.hset("events:" + event_name, "rows", rows)
	redis.hset("events:" + event_name, "seats_per_row", seats_per_row)
	row_name = "A"
	for i in range(rows):
		filled_seat_map = int(math.pow(2,seats_per_row))-1
		redis.set("events:" + event_name + ":" + row_name, struct.pack('l', filled_seat_map))
		row_name = increment_str(row_name)

def get_event_seat_row(event_name, row_name):
	return struct.unpack('l', redis.get("events:" + event_name + ":" + row_name))[0]

def print_event_seat_map(event_name):
	rows = redis.keys("events:" + event_name + ":*")
	for row in rows:
		(_, row_name) = row.rsplit(":",1)
		seat_map = get_event_seat_row(event_name, row_name)
		print("Row {}:").format(row),
		for i in range(seat_map.bit_length()):
			if ((i % 10 ) == 0):
				print "|",
			print (seat_map >> i) & 1,
		print "|"

# Part One - Create the event map
event = "Judo"
create_event(event, 2, 20)
print_event_seat_map(event)

def get_availbale(seat_map, seats_required, first_seat=-1):
	seats = []
	if ( first_seat != -1 ):
		end_seat = first_seat + seats_required -1
	else:
		end_seat = seat_map.bit_length()+1
	required_block = int(math.pow(2,seats_required))-1
	for i in range(1, end_seat+1):
		if ( (seat_map & required_block) == required_block ):
			seats.append( {'first_seat': i, 'last_seat': i + seats_required -1} )
		required_block = required_block << 1
	return seats

def find_seat_selection(event_name, seats_required):
	# Get all the seat rows
	seats = []
	rows = redis.keys("events:" + event_name + ":*")
	for row in rows:
		(_, row_name) = row.rsplit(":",1)
		seat_map = get_event_seat_row(event_name, row_name)
		row_blocks = get_availbale(seat_map, seats_required)
		if (len(row_blocks) > 0):
			seats.append( {'event': event_name, 'row': row_name, 'available': row_blocks } )
	return seats

def print_seat_availbailiy(seats):
	for row in seats:
		print "Event: {}".format(row['event'])
		current_row = row['available']
		for i in range(len(current_row)):
			print "-Row: {}, Start {}, End {}".format(row['row'],current_row[i]['first_seat'], current_row[i]['last_seat'],)

available_seats = find_seat_selection(event, 2)
print_seat_availbailiy(available_seats)

# Part Two - reserve seats
def set_seat_map(event_name, row_name, map):
	redis.set("events:" + event_name + ":" + row_name, struct.pack('l', map))

def generate_order_id():
  return ''.join(random.choice(string.ascii_uppercase + string.digits) \
    for _ in range(6))

class Error(Exception):
    """Base class for exceptions in this module."""
    pass

class SeatTaken(Error):
    def __init__(self, expression, message):
        self.expression = expression
        self.message = message

def reservation(event_name, row_name, first_seat, last_seat):
	reserved = False
	redis.watch("events:" + event_name + ":" + row_name)
	p = redis.pipeline()
	try:
		seat_map = get_event_seat_row(event_name, row_name)
		seats = get_availbale(seat_map, last_seat - first_seat + 1, first_seat)
		if ( len(seats) > 0 ):
			for i in range(first_seat, last_seat+1):
				# Reserve individual seat, raise exception is already reserved
				if (redis.set("orders:" + event_name + ":" + row_name + ":" + str(i), 
					            True,
					            px=5000, nx=True) != True):
					raise SeatTaken(i, "orders:" + event_name + ":" + row_name + ":" + str(i))
			order_id = generate_order_id()
			required_block = int(math.pow(2,last_seat - first_seat + 1))-1 << (first_seat-1)
			redis.set("orders:" + event_name + ":" + row_name + ":" + order_id, 
				        struct.pack('l',required_block),
				        px=5000, nx=True)
			p.bitop("XOR", "events:" + event_name + ":" + row_name, 
				             "events:" + event_name + ":" + row_name, 
				             "orders:" + event_name + ":" + row_name + ":" + order_id)
			p.execute()
			reserved = True
	except WatchError:
		print "Write Conflict: {}".format("events:" + event_name + ":" + row_name)
	except SeatTaken as error:
		print "Seat Taken/{}".format(error.message)
	finally:
		p.reset()
	return reserved

event="Fencing"
create_event(event, 1, 10)
# Seat 4 (the 8th bit) is already sold. We calc this as (2^(seats)-1) - bit_number_of_seat, e.g. 1023 - 8
set_seat_map(event, "A", 1023-8)
print_event_seat_map(event)

seats = find_seat_selection(event, 2)
print_seat_availbailiy(seats)
# Just choose the first found
made_reservation = reservation(event, seats[0]['row'], seats[0]['available'][0]['first_seat'], seats[0]['available'][0]['last_seat'])
print "Made reservation? {}".format(made_reservation)
print_event_seat_map(event)

# Find space for 5 seats
seats = find_seat_selection(event, 5)
print_seat_availbailiy(seats)
# Just choose the first found
made_reservation = reservation(event, seats[0]['row'], seats[0]['available'][0]['first_seat'], seats[0]['available'][0]['last_seat'])
print "Made reservation? {}".format(made_reservation)
print_event_seat_map(event)

# Find space for 2 seat, but not enough inventory
seats = find_seat_selection(event, 2)
if ( len(seats) == 0 ):
	print "Not enough seats"

# Find space for 1 seat
seats = find_seat_selection(event, 1)
# Create a seat reservation (simulating another user), so that the reservation fails
redis.set("orders:" + event + ":" + seats[0]['row'] + ":" + str(seats[0]['available'][0]['first_seat']), True)
made_reservation = reservation(event, seats[0]['row'], seats[0]['available'][0]['first_seat'], seats[0]['available'][0]['last_seat'])
print "Made reservation? {}".format(made_reservation)
print_event_seat_map(event)


