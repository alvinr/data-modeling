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
service1 = "Olympics 2020"
token = "MTOB1J"
service2 = "NBCSports"

# Part One - Provision the device with two services
create_account(device_id)
do_activate({'device': device_id, 'service': service1, 'token': token})
print redis.hgetall("accounts:" + device_id)

do_activate({'device': device_id, 'service': service2, 'token': ""})
print redis.hgetall("accounts:" + device_id)

# Part Two - Entitlement
def do_entitlement(event):
  p = redis.pipeline()
  try:
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

# Entitlement will move the state for "2020 Olympics", if the tokens match
do_entitlement({'device': device_id, 'service': service1, 'token': token})
print "service: {} is {}".format(service1, redis.hget("accounts:" + device_id, "app:" + service1 + ":status"))

# Tokens do not match, so state of "ABC" is moved to Suspended after 3rd failed attempt
for i in range(4):
  do_entitlement({'device': device_id, 'service': service2, 'token': token})
  print "service: {} is {}".format(service2, redis.hget("accounts:" + device_id, "app:" + service2 + ":status"))

# Part Three - Wrap the process into the State Machines
def do_start(event):
  redis.incr("events_oustanding")

def do_finish(event):
  redis.decr("events_oustanding")

def transition(queue, from_state, to_state, invoke):
  # Take the next todo and create new entries into each workflow
  p = redis.pipeline()
  id = redis.brpoplpush("events:" + queue + ":" + from_state, "events:" + queue + ":" + from_state, 1)
  if id != None:
    try:
      redis.watch("event_playload:" + id)
      event = redis.hgetall("event_payload:" + id)
      if event['last_step'] == from_state:
        invoke(event)
        data = { 'ts': long(time.time()), 'last_step': to_state }
        p.hmset("event_payload:" + id, data)
        p.execute()
        print "Executed: Q:{} ID:{} S:{} FN:{}".format(queue, id, from_state, invoke.__name__)
      elif event['last_step'] == to_state:
        p.lrem("events:" + queue + ":" + from_state, 0, id)
        p.lpush("events:" + queue + ":" + to_state, id)
        p.execute()   
        print "Transitioned: Q:{} ID:{} F:{} T:{}".format(queue, id, from_state, to_state)
    except WatchError:
      print "Write Conflict: {}".format("event_payload:" + id)
    finally:
      p.reset()

def process_start(queue):
  transition(queue, from_state="start", to_state="todo", invoke=do_start)

def process_activation(queue):
  transition(queue, from_state="todo", to_state="provision", invoke=do_activate)

def process_entitlement(queue):
  transition(queue, from_state="provision", to_state="entitlement", invoke=do_entitlement)

def process_finish(queue):
  transition(queue, from_state="entitlement", to_state="end", invoke=do_finish)

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

# Process the outstanding todo
while True:
  process_start("new-device")
  process_activation("new-device")
  process_entitlement("new-device")
  process_finish("new-device")
  if int(redis.get("events_oustanding")) == 0:
    break

print redis.hgetall("accounts:" + device_id)

# Part Four - Service threads

def thread_Start(queue):
  while True:
    process_start(queue)

def thread_Activation(queue):
  while True:
    process_activation(queue)

def thread_Entitlement(queue):
  while True:
    process_entitlement(queue)

def thread_Finish(queue):
  while True:
    process_finish(queue)

def wait_for_queues_to_empty():
  while True:
    time.sleep(1)
    if int(redis.get("events_oustanding")) == 0:
      break  

threads = []
threads.append(threading.Thread(target=thread_Start, args=("new-device",)))
threads.append(threading.Thread(target=thread_Activation, args=("new-device",)))
threads.append(threading.Thread(target=thread_Entitlement, args=("new-device",)))
threads.append(threading.Thread(target=thread_Finish, args=("new-device",)))

for i in range(len(threads)):
  threads[i].setDaemon(True)
  threads[i].start()

device_id = "MYTV-999"
create_account(device_id)
# Activation with correct token
create_activation("new-device", device_id, service1, token)

# Activation with 3 incorrect tokens, so Suspend
for i in range(4):
  create_activation("new-device", device_id, service2, "")

wait_for_queues_to_empty()
print redis.hgetall("accounts:" + device_id)

# Activate again, which will generate a new token and transition to Waiting
valid_token = generate_token()
create_activation("new-device", device_id, service2, valid_token)
wait_for_queues_to_empty()
print redis.hgetall("accounts:" + device_id)

# Activation now in Waiting state, so send correct token
create_activation("new-device", device_id, service2, valid_token)
wait_for_queues_to_empty()
print redis.hgetall("accounts:" + device_id)

# Since the tokens expire in 5 seconds, wait 5 seconds and try to activate the ABC again to 
# transition into the Suspended state again
time.sleep(token_expiration)
create_activation("new-device", device_id, service2, valid_token)

wait_for_queues_to_empty()
print redis.hgetall("accounts:" + device_id)



