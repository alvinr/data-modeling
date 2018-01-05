# Inventory
So what if the Rio Olympics ticket inventory control system were built with Aerospike? Awesome! Let's think about the problem at hand. In terms of data and use cases for a booking system, we need to consider the following requirements:
* A ticket can be purchased once and only once
* During the purchase flow, inventory needs to be "held" so that others can't buy tickets for
the same seats at the same time
* If the purchase does not complete, then any "held" inventory needs to be returned to the
available pool
* A user wants to view their purchase

## Simple Purchase

Lets model the ```events``` and the ```users```. Here's an example in JSON:

```
events:
  { name: "Mens 100m Final",
    qty: 495
}

users:
  { name: "Fred",
    purchased: [ { event: "Mens 100m Final", qty: 5} ]
  }
```

So when we come to purchase 5 tickets for this event, it will require two updates: one to decrement the available quantity on the ```event``` record, and a second update to insert into the ```purchased``` array on the ```user``` record. In Python, this would look like:

```python
import aerospike
import os
import time
import random
import string

config = {'hosts': [(os.environ.get('AEROSPIKE_HOST', '127.0.01'), 3000)],
          'policies': { 'key': aerospike.POLICY_KEY_SEND }
}
wpolicy = {'gen': aerospike.POLICY_GEN_EQ}
mpolicy_create = { 'map_write_mode': aerospike.MAP_CREATE_ONLY }

client = aerospike.client(config).connect()

def create_event(event, available):
  client.put(("test", "events", for_event), {'name': event, 'available': available})

def create_user(user):
  client.put(("test", "users", user), {'username': user})

# Part Zero - Purchase as two writes
def simple_purchase(user, event, qty):
  (key, meta, record) = client.get(("test", "events", event))
  client.put( key, {'available': record['available'] - qty},
              {}, wpolicy)
  purchase = { "event": event, 'qty': qty }
  client.list_append(("test", "users", user), "purchased", purchase)

# Simple purchase
requestor = "Fred"
for_event = "Mens 800m Final"
create_user(requestor)
create_event(for_event, 500)
simple_purchase(requestor, for_event, 5)
# Query results
(key, meta, record) = client.get(("test", "users", requestor))
print record
(key, meta, record) = client.get(("test", "events", for_event))
print record
```

As you can see, the ```simple_purchase``` function deducts the quantity requested from the ```event``` and adds a list entry to the ```purchased`` on the ```users``` record.

Running the code, you will see the following output:

```
>>> # Simple purchase
... requestor = "Fred"
>>> for_event = "Mens 800m Final"
>>> create_user(requestor)
>>> create_event(for_event, 500)
>>> simple_purchase(requestor, for_event, 5)
>>> # Query results
... (key, meta, record) = client.get(("test", "users", requestor))
>>> print record
{'username': 'Fred', 'purchased': [{'event': 'Mens 800m Final', 'qty': 5}]} >>> (key, meta, record) = client.get(("test", "events", for_event))
    >>> print record
{'available': 495, 'name': 'Mens 800m Final'}
```

This solution does satisfy the requirement to track purchases. However, splitting the two write operations means that tickets can be decremented from the availability on events, but never added to the ```purchased``` on ```users```­ e.g., if the code crashes between the two statements. That would leave with unsold inventory ­- not a good thing!

## Storing the Purchases Within the Event
We can change the transactional boundary by using the technique of embedding, as shown in an [arlier article](../README.md)e. We can combine the quantity of tickets available along with who the tickets were sold to:

```
events:
  { name: "Mens 100m Final",
    qty: 495,
    sold_to: [ { who: "Fred", qty: 5 } ]
  }
```

We can make use of the Aerospike ```operate``` command, which allows multiple sub­operations to be combined into a single atomic operation to manipulate the structure:

```python
def purchase(user, event, qty):
  (key, meta, record) = client.get(("test", "events", event))
  operations = [
    {
      'op' : aerospike.OPERATOR_WRITE,
      'bin': "available",
      'val': record['available'] - qty
    },
    {
      'op' : aerospike.OP_LIST_APPEND,
      'bin' : "sold_to",
      'val' : {'who': user, 'qty': qty}
    }
  ]
  client.operate(key, operations, meta, wpolicy)

# Purchase valid number of tickets
for_event = "Mens 100m Final"
requested = 5
create_event(for_event, 500)
purchase(requestor, for_event, requested)
# Query results
(key, meta, record) = client.get(("test", "events", for_event))
print record

# Purchase invalid number of tickets
purchase(requestor, for_event, 500)
# Query results
(key, meta, record) = client.get(("test", "events", for_event))
print record
```

The ```purchase``` function reduces the ```available``` tickets and adds the sale onto the ```sold_to``` list. Running the code, you will see the following output:

```
>>> # Purchase valid number of tickets ... for_event = "Mens 100m Final"
>>> requested = 5
>>> create_event(for_event, 500)
>>> purchase(requestor, for_event, requested)
>>> # Query results
... (key, meta, record) = client.get(("test", "events", for_event))
>>> print record
{'available': 495, 'sold_to': [{'who': 'Fred', 'qty': 5}], 'name': 'Mens 100m Final'}
>>>
>>> # Purchase invalid number of tickets
... purchase(requestor, for_event, 500)
>>> # Query results
... (key, meta, record) = client.get(("test", "events", for_event))
>>> print record
{'available': -5, 'sold_to': [{'who': 'Fred', 'qty': 5}, {'who': 'Fred', 'qty': 500}], 'name': 'Mens 100m Final'}
```

So by changing the transaction boundary by embedding the ```sold_to``` within the ```event``` record, we can now atomically change the quantity and add the purchases in one statement. However, over­selling of tickets is possible, as the current availability is not checked before the requested quantity is decremented.


## Checking if Tickets are Available
Thus, we need to check that there is availability before the available stock is updated. But we also need to ensure that another customer does not make a purchase between the check and the update. Let's see how we achieve that:

```python
def check_availability_and_purchase(user, event, qty):
  (key, meta, record) = client.get(("test","events", for_event))
  if record['available'] >= qty:
    operations = [
      {
        'op' : aerospike.OPERATOR_INCR,
        'bin': "available",
        'val': qty * -1
      },
      {
        'op' : aerospike.OP_LIST_APPEND,
        'bin' : "sold_to",
        'val' : {'who': user, 'qty': qty}
      }
    ]
    client.operate(key, operations, meta, wpolicy)

# Check availability before purchasing
# No purchase, not enough stock
for_event = "Womens 4x400m Final"
create_event(for_event, 10)
check_availability_and_purchase(requestor, for_event, 11)
(key, meta, record) = client.get(("test","events", for_event))
print record
```

When you run the code, you will see the following output:

```
>>> # Check availability before purchasing ... # No purchase, not enough stock
... for_event = "Womens 4x400m Final"
>>> create_event(for_event, 10)
>>> check_availability_and_purchase(requestor, for_event, 11)
>>> (key, meta, record) = client.get(("test","events",for_event))
>>> print record
{'available': 10, 'name': 'Womens 4x400m Final'}
>>>
>>>#Purchase, enoughstock
... check_availability_and_purchase(requestor, for_event, 9)
>>> (key, meta, record) = client.get(("test","events",for_event))
>>> print record
{'available': 1, 'sold_to': [{'who': 'Fred', 'qty': 9}], 'name': 'Womens 4x400m Final'}
```

First, the ```event``` record is queried, then we programmatically check if there are sufficient tickets available. Just like in the last example, we atomically update the quantity and add to the list of purchased tickets.

As we described in an earlier post, we have added a policy ```AS_POLICY_GEN_EQ```, which ensures that the version number (or in Aerospike­ speak, “Generation”) is that same version we read when we come to write the record. If the Generations are not the same, then an exception will be thrown, preventing the potential to overwrite an interleaved write, and thus, avoiding overselling the tickets.

## Reserve Stock
Our initial requirements stated that we needed to "hold" or reserve the tickets during the booking process. Just like an airline booking, it would be a poor user experience to get to the end of the payment instructions, just to be told that your tickets have been sold to somebody else. Therefore, we need to include a list of reservationson the events record to keep track of these in­-flight transactions:

```
events:
  { name: "Mens 100m Final",
    qty: 495,
    sold_to: [],
    reservations: {'Fred': {'ts': 1469744519, 'qty': 5}}
  }
```

The reserve function can now do the following:
* Create a reservation if there is sufficient stock
* Perform authorization for the transaction (e.g., via Credit Card)
* Remove the reservation for the event
* Add the sale to the event

```python
def reserve(user, event, qty):
  (key, meta, record) = client.get(("test", "events", event))
  if record['available'] >= qty:
    # Create the reservation and decrement the stock
    operations = [
      {
        'op' : aerospike.OPERATOR_INCR,
        'bin': "available",
        'val': qty * -1
      },
      {
        'op' : aerospike.OP_MAP_PUT,
        'bin': "reservations",
        'key': user,
        'val': { 'qty': qty, 'ts': long(time.time()) },
        'map_policy': mpolicy_create
      }
    ]
    (key, meta, record) = client.operate(key, operations, meta, wpolicy)
    if creditcard_auth(user):
      # Remove the reservation and add the ticket sale
      operations = [
        {
          'op' : aerospike.OP_LIST_APPEND,
          'bin' : "sold_to",
          'val' : { 'who': user, 'qty': qty, 'order': generate_order_id() }
        },
        {
          'op' : aerospike.OP_MAP_REMOVE_BY_KEY,
          'bin' : "reservations",
          'key': user,
          'return_type': aerospike.MAP_RETURN_VALUE
        }
      ]
      client.operate(key, operations, meta, wpolicy)
    else:
      # Back out the reservation on a credit card decline
      backout_reservation(key, meta, user, qty)
```

A couple of helper functions round out the reservation process:

```python
def generate_order_id():
  return ''.join(random.choice(string.ascii_uppercase + string.digits) \
    for _ in range(6))

def creditcard_auth(user):
  # TODO: Credit card auth happens here, but lets just sleep
  # return random.choice([True, False])
  time.sleep(1)
  return True

def backout_reservation(key, meta, user, qty):
  operations = [
    {
      'op' : aerospike.OPERATOR_INCR,
      'bin': "available",
      'val': qty
    },
    {
      'op' : aerospike.OP_MAP_REMOVE_BY_KEY,
      'bin' : "reservations",
      'key': user,
      'return_type': aerospike.MAP_RETURN_NONE
    }
  ]
  return client.operate(key, operations, meta, wpolicy)

# Query results
for_event = "Womens Marathon Final"
create_event(for_event, 500)
reserve(requestor, for_event, 5)
(key, meta, record) = client.get(("test", "events", for_event))
print record
```

Running the code, you will see the following output:
```
>>> # Query results
... for_event = "Womens Marathon Final" >>> create_event(for_event, 500)
>>> reserve(requestor, for_event, 5)
>>> (key, meta, record) = client.get(("test", "events", for_event)) >>> print record
    {'available': 495, 'reservations': {}, 'name': 'Womens Marathon Final', 'sold_to': [{'who': 'Fred', 'order': 'NJXFWB', 'qty': 5}]}
```

The ```reserve``` function contains the main purchase flow. The reservation is made if stock is available, and after a successful credit card authorization (```creditcard_authorization```), the reservation is converted into a sale. In any failure case, the reservation is backed out with the ```backout_reservation``` function.

## Expiring Reservations
So we are only left to deal with expiring reservations, the customer does not complete the purchase, code or machines crash etc.. Given that we set a timestamp when the reservation was made, it becomes pretty simple to check if the reservation has expired: remove that element from the ```reservations``` list and add the quantity reserved back to the total available for the event.

```python
def create_expired_reservation(event):
  reservation = { 'name': event, 
                  'available': 469, 
                  'reservations': { 'Fred': {
                                      'qty': 5, 
                                      'ts': long(time.time())
                                    },
                                    'Jim': { 
                                      'qty': 7, 
                                      'ts': long(time.time() - 50)
                                    },
                                    'Amy': { 
                                      'qty': 19, 
                                      'ts': long(time.time() - 31)
                                    },
                                  }
                }
  client.put(("test", "events", for_event), reservation)

def expire_reservation(event):
  (key, meta, record) = client.get(("test", "events", event))
  # Cutoff is 30 seconds ago
  cutoff_ts = long(time.time()-30)
  for i in record["reservations"]:
    res = record["reservations"][i]
    if res["ts"] < cutoff_ts:
      (key, meta, _) = backout_reservation(key, meta, i, res['qty'])

# Expire reservations
for_event = "Womens Javelin"
create_expired_reservation(for_event)
expire_reservation(for_event)
# Query results
(key, meta, record) = client.get(("test", "events", for_event))
print record
```

When you run the code, you will see the following output:
>>> # Expire reservations
... for_event = "Womens Javelin"
>>> create_expired_reservation(for_event)
>>> expire_reservation(for_event)
>>> # Query results
... (key, meta, record) = client.get(("test", "events", for_event))
>>> print record
{'available': 495, 'reservations': {'Fred': {'ts': 1470848975, 'qty': 5}}, 'name': 'Womens Javelin'}

There are several strategies to deal with concurrency of changes to the same event. In the example above, as each expired reservation is removed, the underlying record is updated. This allows other concurrent processes to manipulate the same record. If there are high concurrent operations on a single record, then it would be expected that a write operation within this loop would fail, because we set the write policy to fail if the Generation on the record had changed. There are many strategies to cope with this, but that's beyond the scope of this article!

## What About My Tickets?
We now have a model to deal with reservations, expiring abandoned reservations and ensuring that ticket can be purchased in a consistent and reliable way. As a customer, I would want to log on and see my tickets. But the purchases are stored on the event. Looping through all events, and then checking what has been sold would be terribly inefficient. So how do we deal with that?
We need to follow a similar pattern that we did for reservations. As part of the write update of the event, we can maintain a list of purchases that need to be pushed back to the user. Using JSON to describe the schema:

```
events:
  { name: "Mens 100m Final",
    qty: 495,
    sold_to: [ { who: "Fred", qty: 5 } ], 
    reservations: { }
    pending : [ { who: "Fred", qty: 5 } ]
  }
```

During the purchase flow, we remove the reservation entry and add the details into the ```sold_to```. We could scan the ```sold_to``` and then check if any user has a missing purchase. Alternatively, as we remove the item out of reservations and into ```sold_to``` ,we can also add to
the list pending. We can now use the ```pending``` list to update each useras an out of band process. The changes to the reservation process are shown below:

```python
def reserve_with_pending(user, event, qty):
  (key, meta, record) = client.get(("test","events",event))
  if record['available'] >= qty:
    # Create the reservation and decrement the stock
    operations = [
      {
        'op' : aerospike.OPERATOR_INCR,
        'bin': "available",
        'val': qty * -1
      },
      {
        'op' : aerospike.OP_MAP_PUT,
        'bin': "reservations",
        'key': user,
        'val': { 'qty': qty, 'ts': long(time.time()) },
        'map_policy': mpolicy_create
      }
    ]
    (key, meta, record) = client.operate(key, operations, meta, wpolicy)
    if creditcard_auth(user):
      # Remove the reservation and add the ticket sale
      order_id = generate_order_id()
      operations = [
        {
          'op' : aerospike.OP_LIST_APPEND,
          'bin' : "sold_to",
          'val' : { 'who': user, 'qty': qty, 'order': order_id }
        },
        {
          'op' : aerospike.OP_MAP_REMOVE_BY_KEY,
          'bin' : "reservations",
          'key': user,
          'return_type': aerospike.MAP_RETURN_VALUE
        },
        {
          'op' : aerospike.OP_LIST_APPEND,
          'bin' : "pending",
          'val' : { 'who': user, 'qty': qty, 'order': order_id}
        }
      ]
      client.operate(key, operations)
    else:
      # Back out the reservation on a credit card decline
      backout_reservation(key, meta, user, qty)
```

Now we can have a sweeper process that adds the purchase to the users ```purchases``` list and then pops the items from the ```pending``` list. We do it in that order in case there is a crash or other change between these two operations. We can re­run this change multiple items, its idempotent.

```python
def post_purchases(event):
  (key, meta, record) = client.get(("test","events",event))
  for res in record["pending"]:
    # Add to users record
    operations = [
      {
        'op' : aerospike.OP_MAP_PUT,
        'bin' : "purchases",
        'key' : res['order'],
        'val' : {'event': event, 'qty': res['qty']}
      }
    ]
    client.operate(("test","users", res['who']), operations)
    operations = [
      {
        'op' : aerospike.OP_LIST_POP,
        'bin' : "pending",
        'index' : 0
      }
    ]
    (key, record, meta) = client.operate(key, operations, meta, wpolicy)

# Post purchases and query results
create_user(requestor)
for_event = "Mens Discus"
create_event(for_event, 500)
reserve_with_pending(requestor, for_event, 5)
post_purchases(for_event)
(key, meta, record) = client.get(("test", "events", for_event))
print record
(key, meta, record) = client.get(("test", "users", requestor))
print record
```

When you run the code, you will see the following output:

```
>>> # Post purchases and query results ... create_user(requestor)
>>> for_event = "Mens Discus"
>>> create_event(for_event, 500)
>>> reserve_with_pending(requestor, for_event, 5)
>>> post_purchases(for_event)
>>> (key, meta, record) = client.get(("test", "events", for_event))
>>> print record
{'available': 495, 'reservations': {}, 'name': 'Mens Discus', 'pending': [], 'sold_to': [{'who': 'Fred', 'order': 'BZWIBD', 'qty': 5}]}
>>> (key, meta, record) = client.get(("test", "users", requestor))
>>> print record
{'username': 'Fred', 'purchases': {'BZWIBD': {'event': 'Mens Discus', 'qty': 5}}}
```

The ```post_purchases``` function adds a map entry onto the ```users``` purchases. The map is keyed by the ```order_id```, so that if this method is executed again, the order is listed once and only once. After the ```user``` record is updated, then we can pop the order from the ```pending``` list on the ```event```.

## Summary
As we have seen, dealing with multi­step transactions is simple. Careful consideration needs to be made around transaction boundaries ­- remember that every record write is atomic, but that there are no multi­statement transaction guarantees. This means you need to approach your domain problem with this in mind, ensuring that multi­step transaction are replayable or you have adequate ways to compensate on failure.

In the next article, we will talk about the [bucketing pattern](../activity_stream/README.md), and how to deal with an activity stream like a Slack or Twitter feed.