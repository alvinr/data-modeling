# Compact Structures
In the [last](../inventory/README.md) article we showed how to storage and manipulate the data for a Ticketing systems, we used the 2020 Olympics as an example. But the events we allowed people to book tickets for did not have any seat allocation or selection. This would be a fine for events like the Marathon where its free standing. But, the Olympics have seated venues and we would like our customers to select seats. So we need to:
* Determine how many tickets they want
* Find the contiguous seats that meet their requirement
* Reserve the seats they requested

## Bitmapped structures
Redis provides [bitmaped structures](https://redis.io/topics/data-types-intro#bitmaps) that can be used for a variety of uses. As we saw in the previous article on [inventory control](../inventory/README.md), we used a bit structure to store a histogram of the total tickets sales by hour. We will adapt model that for this problem, since we can use a single bit to describe if a given seat has been sold. The JSON for the schema looks like:

```
events: "Judo"
  {
  	'availbaility':
  	[
  		{ 'row': "A", 'seat_map': "\b1110111111" },
  		{ 'row': "B", 'seat_map': "\b1111111111" },
  	]
  }
```

We use the binary string to represent the state of each seat in the given row, for example, only seat #4 has been sold in Row "A", represented by the Zero value.

Lets create the code that sets up these structures

```python
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
```

In the function ```create_event``` we set the key for the seating row in the event, but in this case we are setting a binary encoded structure filled with one's to represent each seat that is availbale. So why don't we simply just store the numeric value? Well, the answers is that each language driver will pickle and store the value in a string representation in a meaningful to that language. If we are just using Python or any other specifc language, then that woudl be find. However, if we want to use any of the in-built Redis operators, then we need to store the value in a way that Redis can manipulate, so this is why we use the ```struct.pack``` method to pack the data correctly. This will vary by language on exactly how you do this, but the key point is that you need to store the data in a way that Redis can manipulate.

If you run the code you will see:

```
>>> event = "Judo"
>>> create_event(event, 2, 20)
>>> print_event_seat_map(event)
Row events:Judo:B: | 1 1 1 1 1 1 1 1 1 1 | 1 1 1 1 1 1 1 1 1 1 |
Row events:Judo:A: | 1 1 1 1 1 1 1 1 1 1 | 1 1 1 1 1 1 1 1 1 1 |
```

## Finding blocks of empty seats
Now that we have a bit field to represent the state of each seat, we now need to determine if there are contiguous empty seats that meet the customers request.

```python
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
```

There is nothing specifically Redis here, but inside ```get_availbale``` we use a bit mask of the requested seats to compare the bit field of availbaility. If we don't find a match, we shift the bits by one and continue to check. This implemention is pretty dumb and could be optimized a number of ways, but you will see the basic idea. We build a data structure for the resulting matches that we can use elsewhere in the code - rather than constantly manipulating bit fields!

## Seat Reservation
So once we have found the blocks of seats that meet the customers requests, we can assume that the customer then selects which they want. For that selection we now need to reserve the seats to make the booking. In a similar way to [inventory control](../inventory/README.md) we need to ensure that we reserve all the seats before we complete the booking. Here's the code.

```python
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
```

In the ```reservation``` function we first reserver each of the seats inside the loop. We do this by creating a key, made up of the Event, Row and Seat Number. We pass ```nx=True``` which indicates that the key must not exist. If it does then we thrown a user defined execition ```SeatTaken```. We also set ```px=5000```, which just specifies that they key expires after 5000 miliseconds. In essance, each key acts as a time expired latch. We have to get all latches, one for each seat, in order to compete the order.

After all the seacts are reserved, we then create another time expired key for the ```order```, which contains the seats we reserved. This is then used to update the availbale inventory using the [BITOP]{https://redis.io/commands/bitop} operator. What we are doing is performing an exclusive-OR operation on the seats reserved and the current seat availbaility. This will simply flip the bits for those seats we have just reserved. We put the output back into the same key.

In a multi-step process like this, other clients or customer can be reserving tickets. As we have seen before, we use the [compare and set](https://redis.io/topics/transactions#optimistic-locking-using-check-and-set) meachanism to abort the transation if another process makes a change. In this case, we have created a ```watch``` on the key that represents the row of the event, which contains the seat map. If another process updates the seat map, then this transaction will fail. That way we can put some guarantees on the consistency and integrity of the data we are changing.

Now we can invoke the code to reserve the seats
```python
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
```

Running the code you will see:
```
>>> event="Fencing"
>>> create_event(event, 1, 10)
>>> set_seat_map(event, "A", 1023-8)
>>> print_event_seat_map(event)
Row events:Fencing:A: | 1 1 1 0 1 1 1 1 1 1 |
>>> 
>>> seats = find_seat_selection(event, 2)
>>> print_seat_availbailiy(seats)
Event: Fencing
-Row: A, Start 1, End 2
-Row: A, Start 2, End 3
-Row: A, Start 5, End 6
-Row: A, Start 6, End 7
-Row: A, Start 7, End 8
-Row: A, Start 8, End 9
-Row: A, Start 9, End 10
>>> made_reservation = reservation(event, seats[0]['row'], seats[0]['available'][0]['first_seat'], seats[0]['available'][0]['last_seat'])
>>> print "Made reservation? {}".format(made_reservation)
Made reservation? True
>>> print_event_seat_map(event)
Row events:Fencing:A: | 0 0 1 0 1 1 1 1 1 1 |
```

So what isn't seat #4 available? Well, we set a specific value in ```set_seat_map``` that just marked seat #4 as sold. So the algorithm that checked for availbaility excluded that seat. After the reservation is complete, you can see that seats 1 & 2 are no onger availbale.

Just to test we deal with a seat being taken from under us, we can do the following:
```python
# Find space for 1 seat
seats = find_seat_selection(event, 1)
# Create a seat reservation (simulating another user), so that the reservation fails
redis.set("orders:" + event + ":" + seats[0]['row'] + ":" + str(seats[0]['available'][0]['first_seat']), True)
made_reservation = reservation(event, seats[0]['row'], seats[0]['available'][0]['first_seat'], seats[0]['available'][0]['last_seat'])
print "Made reservation? {}".format(made_reservation)
print_event_seat_map(event)
```

We execute a ```set``` operation in order to create a dummy seat reservation, which will cause the reservation logic to fail:

```
>>> # Find space for 1 seat
>>> seats = find_seat_selection(event, 1)
>>> # Create a seat reservation (simulating another user), so that the reservation fails
>>> redis.set("orders:" + event + ":" + seats[0]['row'] + ":" + str(seats[0]['available'][0]['first_seat']), True)
True
>>> made_reservation = reservation(event, seats[0]['row'], seats[0]['available'][0]['first_seat'], seats[0]['available'][0]['last_seat'])
Seat Taken/orders:Fencing:A:3
>>> print "Made reservation? {}".format(made_reservation)
Made reservation? False
>>> print_event_seat_map(event)
Row events:Fencing:A: | 0 0 1 0 1 1 1 1 1 1 |
```

## Summary
As we have seen, Redis provides ways of dealing with bit orientated structures and reduces the space required to store structures like a seat map. The operators allow for simple manipulation of these structures to simply their use.

In the next article, we will talk about the [bucketing pattern](../activity_stream/README.md), and how to deal with an activity stream like a Slack or Twitter feed.
