import aerospike
import os
import time
import random

config = { 'hosts': [(os.environ.get("AEROSPIKE_HOST", "127.0.01"), 3000)],
           'policies': { 'key': aerospike.POLICY_KEY_SEND }
}
wpolicy = {'gen': aerospike.POLICY_GEN_EQ}
mpolicy = {'map_write_mode': aerospike.MAP_UPDATE}

client = aerospike.client(config).connect()

def activation(event, device, service):
  client.put(("test", "events", event),
             { 'todo': [ { 'service': service, 'device': device }],
               'entitlement': [], 
               'devices': [],
             })

def process_todo(queue):
  (key, meta, record) = client.get(("test", "events", queue))
  # Take the next todo and create new entries into each workflow
  todo = record['todo']
  if len(todo) > 0:
    item = todo[0]
    operations = [
      {
        'op' : aerospike.OP_LIST_POP,
        'bin': "todo",
        'index': 0
      },
      {
        'op' : aerospike.OP_LIST_APPEND,
        'bin': "entitlement",
        'val': { 'device': item['device'], 'service': item['service'], 'ts': 0 }
      },
      {
        'op' : aerospike.OP_LIST_APPEND,
        'bin': "devices",
        'val': { 'device': item['device'], 'service': item['service'], 'ts': 0 }
      }

    ]
    (key, meta, record) = client.operate(key, operations, meta, wpolicy)  

def do_device(item):
# TODO: Call the device processing
  pass

def process_device(queue):
  (key, meta, record) = client.get(("test", "events", queue))
  for i in range(len(record['devices'])):
    # Find a entitlement where the ts=0, i.e. has not been taken
    item = record['devices'][i]
    if item['ts'] == 0:
      item['ts'] = long(time.time())
      operations = [
        {
          'op' : aerospike.OP_LIST_SET,
          'bin' : "devices",
          'index': i,
          'val' : item
        }
      ]
      (key, meta, record) = client.operate(key, operations, meta, wpolicy)
      do_device(item)
      client.list_pop(key, "devices", i, meta, wpolicy)  

def do_entitlement(item):
# TODO: Call the entitlement processing
  pass

def process_entitlement(queue):
  (key, meta, record) = client.get(("test", "events", queue))
  for i in range(len(record['entitlement'])):
    # Find a entitlement where the ts=0, i.e. has not been taken
    item = record['entitlement'][i]
    if item['ts'] == 0:
      item['ts'] = long(time.time())
      operations = [
        {
          'op' : aerospike.OP_LIST_SET,
          'bin' : "entitlement",
          'index': i,
          'val' : item
        }
      ]
      (key, meta, record) = client.operate(key, operations, meta, wpolicy)
      do_entitlement(item)
      client.list_pop(key, "entitlement", i, meta, wpolicy)    

device_id = "ABC-123"

# Create the activation event
activation("new device", device_id, "NBCSports")
# Process the oustanding todo
process_todo("new device")
process_device("new device")
process_entitlement("new device")


