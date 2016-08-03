import aerospike
import os
import time
import random

def auth(device):
  if device['status'] == "Active":
    return random.choice([True, False])
  else:
    return False

config = { 'hosts': [(os.environ.get("AEROSPIKE_HOST", "127.0.01"), 3000)],
           'policies': { 'key': aerospike.POLICY_KEY_SEND }
}
wpolicy = {'gen': aerospike.POLICY_GEN_EQ}
mpolicy = {'map_write_mode': aerospike.MAP_UPDATE}

client = aerospike.client(config).connect()

device_id = "ABC-123"

client.put(("test", "accounts", device_id),
           { 'device_id': device_id,
             'tokens': { 'NBCSports' : {'token': "MTOB1J", 'failed': 0, 'status': "Waiting" } }
           } )

def do_entitlement(device, service, token):
  (key, meta, record) = client.get(("test", "accounts", device_id))
  if service in record['tokens']:
    service_rec = record['tokens'][service]
    if service_rec['token'] == token:
      # Valid, so update last_logon_ts etc
        service_rec['failed'] = 0
        service_rec['last_logon_ts'] = long(time.time())
        service_rec['status'] = 'Active'
        client.map_put(key, "tokens", service, service_rec,
                       mpolicy, meta, wpolicy)
    else:
      if service_rec['status'] in ["Waiting", "Suspended"]:
        if service_rec['failed'] < 3:
          # increment and update last timestamp
          service_rec['failed'] +=1
          service_rec['last_logon_ts'] = long(time.time())
          client.map_put(key, "tokens", service, service_rec,
                         mpolicy, meta, wpolicy)
        else:
          # Exceeded limit
          service_rec['status'] = "Suspended"
          service_rec['last_logon_ts'] = long(time.time())
          client.map_put(key, "tokens", service, service_rec,
                         mpolicy, meta, wpolicy)
      else:
        # Record the attempt, even if the account is suspended
        client.put(key, {'last_logon_ts': long(time.time())})

# Entitlement will fail
do_entitlement(device_id, "NBCSports", "XYZ789")
(key, meta, record) = client.get(("test","accounts",device_id))
print record

# Entitlement will pass
do_entitlement(device_id, "NBCSports", "MTOB1J")
(key, meta, record) = client.get(("test","accounts",device_id))
print record
