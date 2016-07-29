import aerospike
import os
import time

config = { 'hosts': [(os.environ.get("AEROSPIKE_HOST", "127.0.01"), 3000)],
           'policies': { 'key': aerospike.POLICY_KEY_SEND }
}
wpolicy = {'gen': aerospike.POLICY_GEN_EQ}

client = aerospike.client(config).connect()

for_event = "Mens 100m Final"
requestor = "Fred"
requested = 5

reservation = { 'name': for_event, 
                'qty': 469, 
                'reservations': { requestor: {
                                    'qty': requested, 
                                    'ts': long(time.time())
                                  },
                                  'Jim': { 
                                    'qty': 7, 
                                    'ts': long(time.time() - 30)
                                  },
                                  'Amy': { 
                                    'qty': 19, 
                                    'ts': long(time.time() - 31)
                                  },
                                }
              }

client.put(("test", "events", for_event), reservation)
client.put(("test", "users", requestor), {'username': requestor})

# Expire reservations
(key, meta, record) = client.get(("test","events",for_event))

# Cutoff is 30 seconds ago
cutoff_ts = long(time.time()-30)

for i in record["reservations"]:
  res = record["reservations"][i]
  if res["ts"] < cutoff_ts:
    operations = [
      {
        'op' : aerospike.OPERATOR_INCR,
        'bin': "qty",
        'val': res['qty']
      },
      {
        'op' : aerospike.OP_MAP_REMOVE_BY_KEY,
        'bin' : "reservations",
        'key': i,
        'return_type': aerospike.MAP_RETURN_NONE
      }
    ]
    (key, meta, record) = client.operate(("test", "events", for_event), operations, meta, wpolicy)

# Query results
(key, meta, record) = client.get(("test", "events", for_event))
print record
