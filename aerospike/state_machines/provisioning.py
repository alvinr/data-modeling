import aerospike
import os
import time
import random
import string

config = { 'hosts': [(os.environ.get("AEROSPIKE_HOST", "127.0.01"), 3000)],
           'policies': { 'key': aerospike.POLICY_KEY_SEND }
}
wpolicy = {'gen': aerospike.POLICY_GEN_EQ}

client = aerospike.client(config).connect()

device_id = "ABC-123"
service1 = "NBCSports"
service2 = "ABC"

def account(device):
  client.put(("test", "accounts", device),
           {'device_id': device, 'tokens': {} } )

def generate_token():
  return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(6))

def provision(device, service):
  (key, meta, record) = client.get(("test", "accounts", device))
  token = generate_token()
  if service in record['tokens']:
    service = record['tokens'][service]
    if service['status'] in ["New", "Suspended"]:
      client.map_put(key, 'tokens', service, 
                     { 'token': token, 'ts': long(time.time()), 'status': "Waiting" },
                     { 'map_write_mode': aerospike.MAP_UPDATE }, meta, wpolicy)
  else:
    client.map_put(key, 'tokens', service, 
                   { 'token': token, 'ts': long(time.time()), 'status': "Waiting" },
                   { 'map_write_mode': aerospike.MAP_UPDATE }, meta, wpolicy)

account(device_id)

# Provision the device
provision(device_id, service1)
(key, meta, record) = client.get(("test","accounts",device_id))
print record

provision(device_id, service2)
(key, meta, record) = client.get(("test","accounts",device_id))
print record
