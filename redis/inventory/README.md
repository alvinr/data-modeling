# Inventory
So what if the 2020 Olympics ticket inventory control system were built with Redis? Awesome! Let's think about the problem at hand. In terms of data and use cases for a booking system, we need to consider the following requirements:
* A ticket or seat can be purchased once and only once
* During the purchase flow, inventory needs to be "held" so that others can't buy tickets for
the same seats at the same time
* If the purchase does not complete, then any "held" inventory needs to be returned to the
available pool
* A user wants to view their purchase, the sales & marketing teams what to see outstanding inventory and total sales
* User can make multiple purchases for the same event, but not concurrently

## Simple Purchase

Lets model the ```events``` and the ```orders```. Here's an example in JSON:

```
events: "Mens 100m Final"
  { capacity: 500,
    availbale: 495
    price: 9
  }

orders: "Mens 100m Final"
  [
    { 'who': "Fred", 'qty': 5, 'price': 45, 'order_id': "XSFPV5"}
  ]

```

So when we come to purchase 5 tickets for this event, it will require two updates: one to decrement the available quantity on the ```event``` record, and a second update to insert into the ```orders``` lists. In Python, this would look like:

```python
from redis import StrictRedis, WatchError
import os
import time
import random
import string
import json

redis = StrictRedis(host=os.environ.get("REDIS_HOST", "localhost"), 
                    port=os.environ.get("REDIS_PORT", 6379),
                    db=0)
redis.flushall()

# Part One - Check availability and Purchase
def generate_order_id():
  return ''.join(random.choice(string.ascii_uppercase + string.digits) \
    for _ in range(6))

def create_event(event_name, available, price):
  p = redis.pipeline()
  p.hsetnx("events:" + event_name, "capacity", available)
  p.hsetnx("events:" + event_name, "available", available)
  p.hsetnx("events:" + event_name, "price", price)
  p.execute()

def check_availability_and_purchase(user, event_name, qty):
  p = redis.pipeline()
  try:
    redis.watch("events:" + event_name)
    available = int(redis.hget("events:" + event_name, "available"))
    if available >= qty:
      order_id = generate_order_id()
      price = float(redis.hget("events:" + event_name, "price"))
      purchase = { 'who': user, 'qty': qty, 'ts': long(time.time()), 
                   'cost': qty * price, 'order_id': order_id }
      p.hincrby("events:" + event_name, "available", qty * -1)
      p.lpush("orders:" + event_name, json.dumps(purchase))
      p.execute()
  except WatchError:
    print "Write Conflict: {}".format("events:" + event_name)
  finally:
    p.reset()

# Check availability before purchasing
requestor = "Fred"
for_event = "Womens 4x400m Final"
create_event(for_event, 10, 9)
# Purchase, enough stock
check_availability_and_purchase(requestor, for_event, 5)
print redis.lrange("orders:" + for_event, 0, -1)
print redis.hgetall("events:" + for_event)

# No purchase, not enough stock
check_availability_and_purchase(requestor, for_event, 6)
print redis.lrange("orders:" + for_event, 0, -1)
print redis.hgetall("events:" + for_event)
```

As you can see, the ```check_availability_and_purchase``` function deducts the quantity requested from the ```event``` if there is availability and adds a list entry to the ```orders```. Since other ticket sales could happen in parallel, then we use the [compare-and-set pattern](https://redis.io/topics/transactions#optimistic-locking-using-check-and-set) as discussed previously. This means creating a ```watch``` on the event we are reserving tickets for, which will cause the Transaction to fail if the event is changed by the time the ```execute``` in invoked.

Running the code, you will see the following output:

```
>>> # Purchase, enough stock
... check_availability_and_purchase(requestor, for_event, 5)
>>> print redis.lrange("orders:" + for_event, 0, -1)
['{"order_id": "MNMYK5", "who": "Fred", "cost": 45.0, "ts": 1515182462, "qty": 5}']
>>> print redis.hgetall("events:" + for_event)
{'available': '5', 'price': '9', 'capacity': '10'}
>>> 
>>> # No purchase, not enough stock
... check_availability_and_purchase(requestor, for_event, 6)
>>> print redis.lrange("orders:" + for_event, 0, -1)
['{"order_id": "MNMYK5", "who": "Fred", "cost": 45.0, "ts": 1515182462, "qty": 5}']
>>> print redis.hgetall("events:" + for_event)
{'available': '5', 'price': '9', 'capacity': '10'}
```

This solution does satisfy the requirement to track purchases. However, the reality of purchasing tickets, means that there are other asyncronous processes that have to occur during the flow, for example getting a credit card authorization. This means we need to reserve the stock and back out the reservation if the purchase flow fails in any way.

## Reserve Stock
Our initial requirements stated that we needed to "hold" or reserve the tickets during the booking process. Just like an airline booking, it would be a poor user experience to get to the end of the payment instructions, just to be told that your tickets have been sold to somebody else. Therefore, we need to include a list of reservations on the event record to keep track of these in­-flight transactions:

```
events: "Womens Marathon Final"
  { 'capacity: 500,
    'availbale: 495
    'price: 10
    'reservations: 5
    'reservation-user:Fred': 5,
    'reservations-ts:Fred': 1515180820
  }

```
The reserve function can now do the following:
* Create a reservation if there is sufficient stock
* Perform authorization for the transaction (e.g., via Credit Card)
* Remove the reservation for the event
* Add the purchase to the orders list

```python
def reserve(user, event_name, qty):
  p = redis.pipeline()
  try:
    redis.watch("events:" + event_name)
    available = int(redis.hget("events:" + event_name, "available"))
    if available >= qty:
      order_id = generate_order_id()
      price = float(redis.hget("events:" + event_name, "price"))
      p.hincrby("events:" + event_name, "available", qty * -1)
      p.hincrby("events:" + event_name, "reservations", qty)
      p.hsetnx("events:" + event_name, "reservations-user:" + user, qty)
      p.hsetnx("events:" + event_name, "reservations-ts:" + user, long(time.time()))
      p.execute()
  except WatchError:
    print "Write Conflict: {}".format("events:" + event_name)
  finally:
    p.reset()
  if creditcard_auth(user):
    try:
      purchase = { 'who': user, 'qty': qty, 'ts': long(time.time()), 
                   'cost': qty * price, 'order_id': order_id }
      redis.watch("events:" + event_name)
      p.hincrby("events:" + event_name, "reservations", qty * -1)
      p.hdel("events:" + event_name, "reservations-user:" + user)
      p.hdel("events:" + event_name, "reservations-ts:" + user)
      p.lpush("orders:" + event_name, json.dumps(purchase))
      p.execute()
    except WatchError:
      print "Write Conflict: {}".format("events:" + event_name)
    finally:
      p.reset()
  else:
    print "Auth failure on order {} for {}".format(order_id, user)
    backout_reservation(user, event_name, qty)
```

The ```backout_reservation``` function take care of adjusting the ```availbale``` tickets and removing the reservation details.

```python
def backout_reservation(user, event_name, qty):
  p = redis.pipeline()
  try:
    redis.watch("events:" + event_name)
    p.hincrby("events:" + event_name, "available", qty)
    p.hincrby("events:" + event_name, "reservations", qty * -1)
    p.hdel("events:" + event_name, "reservations-user:" + user)
    p.hdel("events:" + event_name, "reservations-ts:" + user)
    p.execute()
  except:
    print "Write Conflict: {}".format("events:" + event_name)
  finally:
    p.reset()
```

We add two items into the ```events``` hash, ```reservation-user``` and ```reservation-ts```. These track who and the time which the reservation was made, which will help to create a process to back out these reservation if a timeout expires or other failure event, which is encapsulated in the ```backout_reservation``` function.

To complete the code, we have a dummy ```creditcard_auth``` function - which just returns a random True/False so that we can see failures occur.

```python
def creditcard_auth(user):
  # TODO: Credit card auth happens here, but lets randomly fail
  return random.choice([True, False])

# Query results
for_event = "Womens Marathon Final"
create_event(for_event, 500, 9)
reserve(requestor, for_event, 5)
print redis.lrange("orders:" + for_event, 0, -1)
print redis.hgetall("events:" + for_event)
```

Running the code, you will see the following output:
```
>>> # Query results
... for_event = "Womens Marathon Final"
>>> create_event(for_event, 500, 9)
>>> reserve(requestor, for_event, 5)
>>> print redis.lrange("orders:" + for_event, 0, -1)
['{"order_id": "HD2TXH", "who": "Fred", "cost": 45.0, "ts": 1515182514, "qty": 5}']
>>> print redis.hgetall("events:" + for_event)
{'available': '495', 'reservations': '0', 'price': '9', 'capacity': '500'}
```

The ```reserve``` function contains the main purchase flow. The reservation is made if stock is available, and after a successful credit card authorization (```creditcard_authorization```), the reservation is converted into a sale. In any failure case, the reservation is backed out with the ```backout_reservation``` function.

## Expiring Reservations
So we are only left to deal with expiring reservations, the customer does not complete the purchase, code or machines crash etc.. Given that we set a timestamp when the reservation was made, it becomes pretty simple to check if the reservation has expired: remove that element from the ```reservations``` list and add the quantity reserved back to the total available for the event.

```python
def expire_reservation(event_name):
  cutoff_ts = long(time.time()-30)
  for i in redis.hscan_iter("events:" + event_name, match="reservations-ts:*"):
    if long(i[1]) < cutoff_ts:
      (_, user) = i[0].split(":")
      qty = int(redis.hget("events:" + event_name, "reservations-user:" + user))
      backout_reservation(user, event_name, qty) 

def create_expired_reservation(event_name):
  p = redis.pipeline()
  p.hset("events:" + event_name, "available", 485)
  p.hset("events:" + event_name, "reservations", 15)
  p.hset("events:" + event_name, "reservations-user:Fred", 3)
  p.hset("events:" + event_name, "reservations-ts:Fred", long(time.time() - 16))
  p.hset("events:" + event_name, "reservations-user:Jim", 5)
  p.hset("events:" + event_name, "reservations-ts:Jim", long(time.time() - 22))
  p.hset("events:" + event_name, "reservations-user:Amy", 7)
  p.hset("events:" + event_name, "reservations-ts:Amy", long(time.time() - 30))
  p.execute() 

# Expire reservations
for_event = "Womens Javelin"
create_expired_reservation(for_event)
expiration = time.time() + 20
while True:
  expire_reservation(for_event)
  oustanding = redis.hmget("events:" + for_event, "reservations-user:Fred", "reservations-user:Jim", "reservations-user:Amy")
  availbale = redis.hget("events:" + for_event, "available")
  print "{}, Available:{}, Reservations:{}".format(for_event, availbale, oustanding)
  if time.time() > expiration:
    break
  else:
    time.sleep(1)
```

When you run the code, you will see the following output:
```
Womens Javelin, Available:492, Reservations:['3', '5', None]
Womens Javelin, Available:492, Reservations:['3', '5', None]
Womens Javelin, Available:492, Reservations:['3', '5', None]
Womens Javelin, Available:492, Reservations:['3', '5', None]
Womens Javelin, Available:492, Reservations:['3', '5', None]
Womens Javelin, Available:492, Reservations:['3', '5', None]
Womens Javelin, Available:492, Reservations:['3', '5', None]
Womens Javelin, Available:492, Reservations:['3', '5', None]
Womens Javelin, Available:497, Reservations:['3', None, None]
Womens Javelin, Available:497, Reservations:['3', None, None]
Womens Javelin, Available:497, Reservations:['3', None, None]
Womens Javelin, Available:497, Reservations:['3', None, None]
Womens Javelin, Available:497, Reservations:['3', None, None]
Womens Javelin, Available:497, Reservations:['3', None, None]
Womens Javelin, Available:500, Reservations:[None, None, None]
Womens Javelin, Available:500, Reservations:[None, None, None]
Womens Javelin, Available:500, Reservations:[None, None, None]
Womens Javelin, Available:500, Reservations:[None, None, None]
Womens Javelin, Available:500, Reservations:[None, None, None]
Womens Javelin, Available:500, Reservations:[None, None, None]
```
As the threshold for the reservation is exceeded, then you can see the reservation backed out until the inventory returns to the initial value of 500.

There are several strategies to deal with concurrency of changes to the same event. In the example above, as each expired reservation is removed, the underlying record is updated. This allows other concurrent processes to manipulate the same record. If there are high concurrent operations on a single event, then it would be expected that a write operation within this loop would fail, because of the ```watch``` that was set. There are many strategies to cope with this, but that's beyond the scope of this article!

## What About My Tickets?
We now have a model to deal with reservations, expiring abandoned reservations and ensuring that ticket can be purchased in a consistent and reliable way. As a customer, I would want to log on and see my tickets. But the purchases are stored on a single list. Looping through all orders, and then checking what has been sold to who would be terribly inefficient. So how do we deal with that?
We need to follow a similar pattern that we did for reservations. As part of the write update of the event, we can maintain a list of purchases that need to be pushed back to the user and event. Using JSON to describe the schema:

```
events: "Mens Discus"
  { 'capacity: 500,
    'availbale: 495
    'price: 10
  }

purchase_orders: "HD2TXH"
   { 'who': "Fred", 
     'qty': qty, 
     'ts': 1515180820, 
     'cost': 50, 
     'event': "Mens Discus"
  }

invoices: "Fred"
  [ "HD2TXH" ]

sales: "Mens Discus"
  [ "HD2TXH" ]
```

During the purchase flow, we remove the reservation entry and add the details into the ```purchase_orders```. We then add the ```order_id``` into both the ```invoices``` list for the user and the ```sales``` list for the event.

First lets deal with storing the ```purchase_order``` and pushing the ```order_id``` in the ```pending``` queue.

```python
def reserve_with_pending(user, event_name, qty):
  p = redis.pipeline()
  try:
    redis.watch("events:" + event_name)
    available = int(redis.hget("events:" + event_name, "available"))
    if available >= qty:
      order_id = generate_order_id()
      price = float(redis.hget("events:" + event_name, "price"))
      p.hincrby("events:" + event_name, "available", qty * -1)
      p.hincrby("events:" + event_name, "reservations", qty)
      p.hsetnx("events:" + event_name, "reservations-user:" + user, qty)
      p.hsetnx("events:" + event_name, "reservations-ts:" + user, long(time.time()))
      p.execute()
  except WatchError:
    print "Write Conflict: {}".format("events:" + event_name)
  finally:
    p.reset()
  if creditcard_auth(user):
    try:
      purchase = { 'who': user, 'qty': qty, 'ts': long(time.time()), 'cost': qty * price, 
                   'order_id': order_id, 'event': event_name }
      redis.watch("events:" + event_name)
      p.hincrby("events:" + event_name, "reservations", qty * -1)
      p.hdel("events:" + event_name, "reservations-user:" + user)
      p.hdel("events:" + event_name, "reservations-ts:" + user)
      p.set("purchase_orders:" + order_id, json.dumps(purchase))
      p.lpush("pending:" + event_name, order_id)
      p.execute()
    except WatchError:
      print "Write Conflict: {}".format("events:" + event_name)
    finally:
      p.reset()
  else:
    print "Auth failure on order {} for {}".format(order_id, user)
    backout_reservation(user, event_name, qty)
```

Now we can have a sweeper process that adds the purchase to the ```invoices``` for the user and the ```sales``` for the event, by poping the next item from the ```pending``` list.

```python
def post_purchases(event_name):
  order_id = redis.rpop("pending:" + event_name)
  if order_id != None:
    p = redis.pipeline()
    order = json.loads(redis.get("purchase_orders:" + order_id))
    p.sadd("invoices:" + order['who'], order_id)
    p.sadd("sales:" + event_name, order_id)
    p.hincrbyfloat("sales_summary", event_name + ":total_sales", order['cost'])
    p.hincrby("sales_summary", event_name + ":total_tickets_sold", order['qty'])
    p.execute()
```

Since the Sales and Marketing teams also want to know the total sales and availbale tickets for the event, we maintain two counters in the hash ```sales_summary```. It should be noted, that simply popping the ```pending``` queue could result in the loss of this event if a crash or other event was to occur. As we saw in the [state machine](../state_mchines/README.md) article, there are patterns to deal with this problem, so will omit here for sake of clarity.

We can now create a new events and purchases:

```
events = [
            { 'event': "Mens Discus", 'qty': 200, 'price': 10, 
              'buys' : [ { 'who': "Fred", 'required': 5 }, { 'who': "Amy", 'required': 2 } ] }, 
            { 'event': "Womens Discus", 'qty': 500, 'price': 15, 
              'buys': [ { 'who': "Jim", 'required': 20 }, { 'who': "Amy", 'required': 17 } ] }
          ]

for next_event in events:
  create_event(next_event['event'], next_event['qty'], next_event['price'])
  for buy in next_event['buys']:
    reserve_with_pending(buy['who'], next_event['event'], buy['required'])
    post_purchases(next_event['event'])

for next_event in events:
  print "=== Event: {}".format(next_event['event'])
  print "Details: {}".format(redis.hgetall("events:" + next_event['event']))
  print "Sales: {}".format(redis.smembers("sales:" + next_event['event']))
  for buy in next_event['buys']:
    print "Invoices for {}: {}".format(buy['who'], redis.smembers("invoices:" + buy['who']))

print "=== Orders"
for i in redis.scan_iter(match="purchase_orders:*"):
  print redis.get(i)  

print "=== Sales Summary \n{}".format(redis.hgetall("sales_summary"))

```

When you run the code, you will see the following output:

```
=== Event: Mens Discus
Details: {'available': '193', 'reservations': '0', 'price': '10', 'capacity': '200'}
Sales: set(['N4PS8S', '2P3C8S'])
Invoices for Fred: set(['N4PS8S'])
Invoices for Amy: set(['9VJW3N', '2P3C8S'])
=== Event: Womens Discus
Details: {'available': '463', 'reservations': '0', 'price': '15', 'capacity': '500'}
Sales: set(['9VJW3N', 'RWK24C'])
Invoices for Jim: set(['RWK24C'])
Invoices for Amy: set(['9VJW3N', '2P3C8S'])
>>> print "=== Orders"
=== Orders
>>> for i in redis.scan_iter(match="purchase_orders:*"):
...   print redis.get(i)  
... 
{"order_id": "2P3C8S", "who": "Amy", "ts": 1515184515, "qty": 2, "cost": 20.0, "event": "Mens Discus"}
{"order_id": "9VJW3N", "who": "Amy", "ts": 1515184517, "qty": 17, "cost": 255.0, "event": "Womens Discus"}
{"order_id": "N4PS8S", "who": "Fred", "ts": 1515184514, "qty": 5, "cost": 50.0, "event": "Mens Discus"}
{"order_id": "RWK24C", "who": "Jim", "ts": 1515184516, "qty": 20, "cost": 300.0, "event": "Womens Discus"}
>>> print "=== Sales Summary \n{}".format(redis.hgetall("sales_summary"))
=== Sales Summary 
{'Mens Discus:total_sales': '70', 'Womens Discus:total_tickets_sold': '37', 'Womens Discus:total_sales': '555', 'Mens Discus:total_tickets_sold': '7'}
```

## Summary
As we have seen, dealing with multi­step transactions is simple. Careful consideration needs to be made around transaction boundaries ­- remember that value smay be morphed by another process between reading and modifying a value. This means you need to approach your domain problem with this in mind, ensuring that multi­step transaction are replayable or you have adequate ways to compensate on failure.

In the next article, we will talk about the [bucketing pattern](../activity_stream/README.md), and how to deal with an activity stream like a Slack or Twitter feed.