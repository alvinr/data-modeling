# State Machines & Queues
A common data pattern revolves around managing state and ensuring that transitions between states happen in a consistent way. This could be anything from a fulfillment process to workflows or other systems where you need to maintain state.

## Provisioning
Let's consider a simple provisioning system (see Figure­-1); it could be a signup form for a new web site, or automatic provisioning of infrastructure, etc. In this example, let's consider setting up your new Apple TV, Amazon Fire TV or Android TV device, and using one of the applications such as "NBC Sports".

![Alt text](figure-1.png "Figure­-1: State Machine for managing relationship end transfer")

**Figure­-1: State Machine for managing relationship end transfer**

The first time you use the "NBC Sports" application on the device, you are presented on screen with a Activation code. You then go the provider's web site with the code, enter it and after it performs a succesful entitlement request to your cable provider, the application is activated.

As can be seen from the state diagram, each of these distinct steps is modeled as a state the system needs to track. Let's looks at a simple JSON representation of this schema:

```
account: "ATV-123"
  { 'created_at': 1469744519
    'app': {
      'NBCSports': { 'token': "MTOB1J", 
                     'status': "Active", 
                     'expires': 1514938817 }
    }
  }
```

The code required to provision the device is straightforward:

```python
from redis import StrictRedis, WatchError
import os
import time
import random
import string
import json
import uuid
import threading

redis = StrictRedis(host=os.environ.get("REDIS_HOST", "localhost"), 
                    port=os.environ.get("REDIS_PORT", 6379),
                    db=0)
redis.flushall()

# Short expiration, to allow simpler testing, but this could be any value (e.g. 28 days)
token_expiration = 5

def create_account(device):
  redis.hset("accounts:" + device, 'created_at', long(time.time()))

def generate_token():
  return ''.join(random.choice(string.ascii_uppercase + string.digits) \
    for _ in range(6))

def do_activate(event):
  if event['token'] == "":
    event['token'] = generate_token()
  try:
    p = redis.pipeline()
    redis.watch("accounts:" + event['device'])
    account = redis.hgetall("accounts:" + event['device'])
    if 'app:' + event['service'] not in account.keys():
      data = {}
      data['app:' + event['service'] + ':status'] = "Waiting"
      data['app:' + event['service'] + ':failed'] = 0
      p.hmset("accounts:" + event['device'], data)
      p.hsetnx("accounts:" + event['device'], 'app:' + event['service'], event['token'])
      p.execute()
  except WatchError:
    print "Write Conflict: {}".format("accounts:" + event['device'])
  finally:
    p.reset()

device_id = "ATV-123"
service1 = "NBCSports"
token = "MTOB1J"
service2 = "ABC"

# Part One - Provision the device with two services
create_account(device_id)
do_activate({'device': device_id, 'service': service1, 'token': token})
print redis.hgetall("accounts:" + device_id)

do_activate({'device': device_id, 'service': service2, 'token': ""})
print redis.hgetall("accounts:" + device_id)
```

In order to track the activation token used by each application, we create a hash structure. This allows a simple keyed access, so we can directly access the entry for "NBCSports", without the need to iterate through a list. As we can see in the ```do_activate``` function, we can directly access the correct item in the hash. Per the state diagram in Figure­-1, the activation is put in the "Waiting" state, ready for the next steps.

When you run the code, you will see the following:

```
>>> create_account(device_id)
>>> do_activate({'device': device_id, 'service': service1, 'token': token})
>>> print redis.hgetall("accounts:" + device_id)
{'app:NBCSports': 'MTOB1J', 'created_at': '1514939717', 'app:NBCSports:failed': '0', 'app:NBCSports:status': 'Waiting'}
>>> 
>>> do_activate({'device': device_id, 'service': service2, 'token': ""})
>>> print redis.hgetall("accounts:" + device_id)
{'app:ABC:failed': '0', 'app:NBCSports:status': 'Waiting', 'app:NBCSports': 'MTOB1J', 'created_at': '1514939717', 'app:ABC': 'Y4285X', 'app:ABC:status': 'Waiting', 'app:NBCSports:failed': '0'}
>>> 

```

## Avoiding Updates by Other Threads and Processes
Since we are first reading the hash and then setting values at a later stage, we use the [compare-and-set pattern](https://redis.io/topics/transactions#optimistic-locking-using-check-and-set). Distilling the code from above we have the following pattern:

```python
my_key = 123
try:
  p = redis.pipeline()
  redis.watch(my_key)
  # any key updates are put here
  p.execute()
except WatchError:
  print "Write Conflict: {}".format(my_key)
finally:
  p.reset()
```

First a ```watch``` is created for the key we are interested in, we can then continue to set values within a Transaction (and since this is Python, we use the ```pipeline``` construct) until the Transaction is executed. If the key was changed, then an exception will be thrown when the transaction is executed. There are several ways we can deal with that (e.g., re­query the record and try the transaction again, return an error to the user, compensate on failure etc.), but that is beyond the scope of this article. The key point is that you can track these changes  - and act on them - programmatically.

## Tracking Service Activation Attempts
When a service tries to activate, then we want to track the following:
* Valid token for activation
* Invalid toekn for activation
** Attempts are <= 3
** Attempts are > 3

Lets look at the code to support this entitlement flow:

```python
def do_entitlement(event):
  try:
    p = redis.pipeline()
    redis.watch("accounts:" + event['device'])
    account = redis.hgetall("accounts:" + event['device'])
    if 'app:' + event['service'] in account.keys():
      service_rec = {}
      if account['app:' + event['service'] + ':status'] == "Waiting":
        if account['app:' + event['service']] == event['token']:
          # Matching token, activate service
          service_rec['app:' + event['service'] + ':failed'] = 0
          service_rec['app:' + event['service'] + ':status'] = 'Active' 
          p.hmset("accounts:" + event['device'], service_rec)
          p.hsetnx("accounts:" + event['device'], 'app:' + event['service'] + ':expires', long(time.time() + token_expiration))
          p.execute()       
        else:
          # Token not matched, determine if the account needs to be suspended
          if int(account['app:' + event['service'] + ':failed']) < 3:
            # increment and update last timestamp
            p.hincrby("accounts:" + event['device'], 'app:' + event['service'] + ':failed', 1)
            p.execute()
          else:
            # Exceeded limit
            service_rec['app:' + event['service'] + ':status'] = "Suspended"
            p.hmset("accounts:" + event['device'], service_rec)
            p.execute()
      elif account['app:' + event['service'] + ':status'] == "Active":
        if long(account['app:' + event['service'] + ':expires']) >= long(time.time()):
          # Token not expired, so update
          service_rec['app:' + event['service'] + ':failed'] = 0
          p.hmset("accounts:" + event['device'], service_rec)
          p.execute()
        else:
          # Token expired, so suspend
          service_rec['app:' + event['service'] + ':failed'] = 0
          service_rec['app:' + event['service'] + ':status'] = 'Suspended' 
          p.hmset("accounts:" + event['device'], service_rec)
          p.hdel("accounts:" + event['device'], 'app:' + event['service'] + ':expires')
          p.execute()
      elif account['app:' + event['service'] + ':status'] == "Suspended":
        # Generate new Token and transition back to Waiting state
        if event['token'] == "":
          service_rec['app:' + event['service']] = generate_token()
        else:
          service_rec['app:' + event['service']] = event['token']
        service_rec['app:' + event['service'] + ':failed'] = 0
        service_rec['app:' + event['service'] + ':status'] = 'Waiting' 
        p.hmset("accounts:" + event['device'], service_rec)
        p.execute()
  except WatchError:
    print "Write Conflict: {}".format("accounts:" + event['device'])
  finally:
    p.reset()

# Entitlement will move the state for "NBCSports", if the tokens match
do_entitlement({'device': device_id, 'service': service1, 'token': token})
print "service: {} is {}".format(service1, redis.hget("accounts:" + device_id, "app:" + service1 + ":status"))
```

The ```do_entitlement``` function transitions to the various states, depending on the evaluation of the current state. When you run the code, you will see the following:

```
>>> do_entitlement({'device': device_id, 'service': service1, 'token': token})
>>> print "service: {} is {}".format(service1, redis.hget("accounts:" + device_id, "app:" + service1 + ":status"))
service: NBCSports is Active
```

We can also test the state transition when we exceed the number of attempts:
```
>>> # Tokens do not match, so state of "ABC" is moved to Suspended after 3rd failed attempt
... for i in range(4):
...   do_entitlement({'device': device_id, 'service': service2, 'token': token})
...   print "service: {} is {}".format(service2, redis.hget("accounts:" + device_id, "app:" + service2 + ":status"))
... 
service: ABC is Waiting
service: ABC is Waiting
service: ABC is Waiting
service: ABC is Suspended
```

## Queues
Queues are a common structure when you need some guarantees of order, especially when you are processing a set of events with many separate processes or threads.

## Tracking Devices
Let's say the marketing team at NBC wanted to know every new service activation so that they could send you an offer. You would not want to hold up the activation process from happening, so this means that the activation now consists of two things:
* Activate the service for the device
* Add the device as eligible for offers, etc.

There are several ways to model this, but for our example, let's use a queue. What we will do is use the service activation request event to add an item to a queue. Then, all the interested processes can use this record to trigger subsequent processing. This means that we do not need multi­record transactions to activate and extend offers. We have one record that several separate processes can now manipulate independently. 

![Alt text](figure-2.png "Figure­-2: State Machine for queue flow")

**Figure­-2: State Machine for queue flow**


Here's an example of what that would look like in JSON:

```
events: "todo"
  [ "ea498100-bd87-48dc-bb0d-79064ee6d8c4" ]

events: "provision"
  [ ]

events: "entitlement"
  [ ]

event_payload: "ea498100-bd87-48dc-bb0d-79064ee6d8c4"
  { 'service': "NBC Sports", 
    'device': "ABC-123", 
    'token': "MTOB1J",
    'last_step': "start",
    'ts': 0
  }

```

In the above example, we are going to use the ```todo``` list to track new incoming requests and the ```provision``` and ```entitlement``` lists to track the separate workflows. The ```event_payload``` is used to store the details about the actual event being processed, in a hash to allow for simple acccess to the individual attributes. The queues themselves simple contain the unique ID of the event store din ```event_payload```.

Let's take a look at the code to support this:

```python
def transition(queue, from_state, to_state, fn):
  # Take the next todo and create new entries into each workflow
  id = redis.brpoplpush("events:" + queue + ":" + from_state, "events:" + queue + ":" + from_state, 1)
  if id != None:
    try:
      p = redis.pipeline()
      redis.watch("event_playload:" + id)
      event = redis.hgetall("event_payload:" + id)
      if event['last_step'] == from_state:
        fn(event)
        data = { 'ts': long(time.time()), 'last_step': to_state }
        p.hmset("event_payload:" + id, data)
        p.execute()
        print "Executed: Q:{} ID:{} S:{} FN:{}".format(queue, id, from_state, fn.__name__)
      elif event['last_step'] == to_state:
        p.lrem("events:" + queue + ":" + from_state, 0, id)
        p.lpush("events:" + queue + ":" + to_state, id)
        p.execute()   
        print "Transitioned: Q:{} ID:{} F:{} T:{}".format(queue, id, from_state, to_state)
    except WatchError:
      print "Write Conflict: {}".format("event_payload:" + id)
    finally:
      p.reset()  
```

The ```transition`` function handles the queues and the transition of tasks between the queues. We use [```BRPOPLPUSH```](https://redis.io/commands/brpoplpush) to form a [circular list](https://redis.io/commands/rpoplpush#pattern-circular-list), as wepop the next item we add back on the end of the list. The ```B```blocking version of this function simply will wait for an item to be added to the list, or for the timeout to occur (which we set to 1 second to make testing simpler). The first time we see the ```event``` we invoke the function ```fn()``` that is passed as a parameter and update the hash on compeltion. The second time we see the ```event``` we remove it from the source list and add it to the traget list, if effect transitionign the state of the ```event``` and making it ready for the next step in the process.


Each state handler is then defined in a simple wrapper function of the ```transition``` function, specifiying the from and to states, plus the function to execute.

```python
def process_start(queue):
  transition(queue, "start", "todo", do_start)

def process_activation(queue):
  transition(queue, "todo", "provision", do_activate)

def process_entitlement(queue):
  transition(queue, "provision", "entitlement", do_entitlement)

def process_finish(queue):
  transition(queue, "entitlement", "end", do_finish)
```

To complete the code for the device workflow:

```python
def create_activation(queue, device, service, token):
  data = { 'service': service, 
           'device': device, 
           'token': token,
           'last_step': "start",
           'ts': 0
          }
  id = str(uuid.uuid4())
  p = redis.pipeline()
  p.rpush("events:" + queue + ":start", id)
  p.hmset("event_payload:" + id, data)
  # p.expire("event_payload:" + id, 120)
  p.execute()

# Create the activation event
device_id = "MYTV-678"
create_account(device_id)
create_activation("new-device", device_id, "CNN", token)
```

Now the ```event``` has been created, we need to call the functions that will process the events. In reality, these would be encapsulated in Threads that would process the queues, the complete code for that is inlcuded in the [source files](./all.py). Here's a simple loop to process the oustanding events.

```python
# Process the outstanding todo
while True:
  process_start("new-device")
  process_activation("new-device")
  process_entitlement("new-device")
  process_finish("new-device")
  if int(redis.get("events_oustanding")) == 0:
    break

print redis.hgetall("accounts:" + device_id)
```

When the code is run, you will see the following output

```
>>> # Process the outstanding todo
... while True:
...   process_start("new-device")
...   process_activation("new-device")
...   process_entitlement("new-device")
...   process_finish("new-device")
...   if int(redis.get("events_oustanding")) == 0:
...     break
... 
Executed: Q:new-device ID:bd506063-20af-456f-aaea-07228b5ca648 S:start FN:do_start
Transitioned: Q:new-device ID:bd506063-20af-456f-aaea-07228b5ca648 F:start T:todo
Executed: Q:new-device ID:bd506063-20af-456f-aaea-07228b5ca648 S:todo FN:do_activate
Transitioned: Q:new-device ID:bd506063-20af-456f-aaea-07228b5ca648 F:todo T:provision
Executed: Q:new-device ID:bd506063-20af-456f-aaea-07228b5ca648 S:provision FN:do_entitlement
Transitioned: Q:new-device ID:bd506063-20af-456f-aaea-07228b5ca648 F:provision T:entitlement
Executed: Q:new-device ID:bd506063-20af-456f-aaea-07228b5ca648 S:entitlement FN:do_finish

>>> print redis.hgetall("accounts:" + device_id)
{'app:CNN:expires': '1514999299', 'created_at': '1514999288', 'app:CNN': 'MTOB1J', 'app:CNN:status': 'Active', 'app:CNN:failed': '0'}

```

# Summary
As you can see, building and manipulating data models to support state machines, queues and other structures is straight-forward with Redis.

In the [next article](../inventory/README.md), we will discuss how to manage a finite (and perishable) resource like tickets sales for the Olympics, and how to deal with reservations that you may need to back out on.