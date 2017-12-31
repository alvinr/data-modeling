from redis import StrictRedis
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

def create_account(device):
  redis.hset("accounts:" + device, 'created_at', long(time.time()))

def generate_token():
  return ''.join(random.choice(string.ascii_uppercase + string.digits) \
    for _ in range(6))

def do_provision(event):
  if event['token'] == "":
    event['token'] = generate_token()
  redis.watch("accounts:" + event['device'])
  account = redis.hgetall("accounts:" + event['device'])
  if 'app:' + event['token'] in account.keys():
    if account['app:' + event['service'] + ":status"] in ["New", "Suspended"]:
      p = redis.pipeline()
      data = {}
      data['app:' + event['service'] + ':ts'] = long(time.time())
      p.hmset("accounts:" + event['device'], data)
      p.execute()
  else:
    p = redis.pipeline()
    p.hsetnx("accounts:" + event['device'], 'app:' + event['service'], event['token'])
    data = {}
    data['app:' + event['service'] + ':ts'] = long(time.time())
    data['app:' + event['service'] + ':status'] = "Waiting"
    data['app:' + event['service'] + ':failed'] = 0
    p.hmset("accounts:" + event['device'], data)
    p.execute()

device_id = "ATV-123"
service1 = "NBCSports"
token = "MTOB1J"
service2 = "ABC"

# Part One - Provision the device
create_account(device_id)
do_provision({'device': device_id, 'service': service1, 'token': token})
print redis.hgetall("accounts:" + device_id)

do_provision({'device': device_id, 'service': service2, 'token': ""})
print redis.hgetall("accounts:" + device_id)

# Part Two - Entitlement
def do_entitlement(event):
  redis.watch("accounts:" + event['device'])
  account = redis.hgetall("accounts:" + event['device'])
  if 'app:' + event['service'] in account.keys():
    service_rec = {}
    if account['app:' + event['service']] == token:
      # Valid, so update last_logon_ts etc
        p = redis.pipeline()
        service_rec['app:' + event['service'] + ':failed'] = 0
        service_rec['app:' + event['service'] + ':last_logon_ts'] = long(time.time())
        service_rec['app:' + event['service'] + ':status'] = 'Active'
        p.hmset("accounts:" + event['device'], service_rec)
        p.execute()
    else:
      if account['app:' + event['service'] + ':status'] in ["Waiting", "Suspended"]:
        if account['app:' + event['service'] + ':failed'] < 3:
          # increment and update last timestamp
          p = redis.pipeline()
          p.hset("accounts:" + event['device'], 'app:' + event['service'] + ':last_logon_ts', long(time.time()))
          p.hincrby("accounts:" + event['device'], 'app:' + event['service'] + ':failed', 1)
          p.execute()
        else:
          # Exceeded limit
          p = redis.pipeline()
          service_rec['app:' + event['service'] + ':status'] = "Suspended"
          service_rec['app:' + event['service'] + ':last_logon_ts'] = long(time.time())
          p.hmset("accounts:" + event['device'], service_rec)
          p.execute()
      else:
          # Record the attempt, even if the account is suspended
          p = redis.pipeline()
          p.hset("accounts:" + event['device'], 'app:' + event['service'] + ':last_logon_ts', long(time.time()))
          p.hincrby("accounts:" + event['device'], 'app:' + event['service'] + ':failed', 1)
          p.execute()

# Entitlement will move the state for "NBCSports", if the tokens match
do_entitlement({'device': device_id, 'service': service1, 'token': token})
print redis.hgetall("accounts:" + device_id)

# Tokens do not match, so state of "ABC" is unchanged
do_entitlement({'device': device_id, 'service': service2, 'token': token})
print redis.hgetall("accounts:" + device_id)

# Part Three - Wrap the process into the State Machines
def do_start(event):
  redis.incr("events_oustanding")

def do_finish(event):
  redis.decr("events_oustanding")

def transition(queue, from_state, to_state, fn):
  # Take the next todo and create new entries into each workflow
  id = redis.brpoplpush("events:" + queue + ":" + from_state, "events:" + queue + ":" + from_state, 1)
  # id = redis.rpoplpush("events:" + queue + ":" + from_state, "events:" + queue + ":" + from_state)
  if id != None:
    redis.watch("event_playload:" + id)
    event = redis.hgetall("event_payload:" + id)
    if event['last_step'] == from_state:
      fn(event)
      data = { 'ts': long(time.time()), 'last_step': to_state }
      p = redis.pipeline()
      p.hmset("event_payload:" + id, data)
      p.execute()
      print "Q:{} F:{} T:{} ID:{}".format(queue, from_state, to_state, id)
    elif event['last_step'] == to_state:
      p = redis.pipeline()
      p.lrem("events:" + queue + ":" + from_state, 0, id)
      p.lpush("events:" + queue + ":" + to_state, id)
      p.execute()   
      print "Q:{} F:{} T:{} ID:{}".format(queue, from_state, to_state, id)

def process_start(queue):
  transition(queue, "start", "todo", do_start)

def process_provision(queue):
  transition(queue, "todo", "provision", do_provision)

def process_entitlement(queue):
  transition(queue, "provision", "entitlement", do_entitlement)

def process_finish(queue):
  transition(queue, "entitlement", "end", do_finish)

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
create_activation("new-device", device_id, "NBCSports", token)

# Process the outstanding todo
while True:
  process_start("new-device")
  process_provision("new-device")
  process_entitlement("new-device")
  process_finish("new-device")
  if int(redis.get("events_oustanding")) == 0:
    break

print redis.hgetall("accounts:" + device_id)

# Part Four - Service threads

def threadStart(queue):
  while True:
    process_start(queue)

def threadProvision(queue):
  while True:
    process_provision(queue)

def threadEntitlement(queue):
  while True:
    process_entitlement(queue)

def threadFinish(queue):
  while True:
    process_finish(queue)

threads = []
threads.append(threading.Thread(target=threadStart, args=("new-device",)))
threads.append(threading.Thread(target=threadProvision, args=("new-device",)))
threads.append(threading.Thread(target=threadEntitlement, args=("new-device",)))
threads.append(threading.Thread(target=threadFinish, args=("new-device",)))

device_id = "MYTV-999"
create_account(device_id)
create_activation("new-device", device_id, "NBCSports", token)
create_activation("new-device", device_id, "ABC", "")
create_activation("new-device", device_id, "Velocity", "")
create_activation("new-device", device_id, "Velocity", "")
create_activation("new-device", device_id, "Velocity", "")
create_activation("new-device", device_id, "Velocity", "")

for i in range(len(threads)):
  threads[i].setDaemon(True)
  threads[i].start()

while True:
  time.sleep(1)
  if int(redis.get("events_oustanding")) == 0:
    break

print redis.hgetall("accounts:" + device_id)

for i in range(len(threads)):
  threads[i].stop()




