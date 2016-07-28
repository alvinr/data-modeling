import aerospike
import os
import time

config = { 'hosts': [(os.environ.get("AEROSPIKE_HOST", "127.0.01"), 3000)] }
wpolicy = {'gen': aerospike.POLICY_GEN_EQ}

client = aerospike.client(config).connect()

for_event = "Mens 100m Final"
requestor = "Fred"
requested = 5

reservation = { 'name': for_event, 
                'qty': 469, 
                'reservations': [ { 'who': requestor, 
                                    'qty': requested, 
                                    'ts': long(time.time())
                                  },
                                  { 'who': "Jim", 
                                    'qty': 7, 
                                    'ts': long(time.time() - 30)
                                  },
                                  { 'who': "Amy", 
                                    'qty': 19, 
                                    'ts': long(time.time() - 31)
                                  },
                                ]
              }
operations = [
  {
    'op' : aerospike.OPERATOR_WRITE,
    'bin': "name",
    'val': for_event
  },
  {
    'op' : aerospike.OPERATOR_WRITE,
    'bin': "qty",
    'val': 469
  },
  {
    'op' : aerospike.OP_MAP_PUT,
    'bin': "reservations",
    'key': requestor
    'val': { 'qty': requested, 'ts': long(time.time() }
  },
  {
    'op' : aerospike.OP_MAP_PUT,
    'bin': "reservations",
    'key': "Jim"
    'val': { 'qty': 7, 'ts': long(time.time()-31 }
  },
  {
    'op' : aerospike.OP_MAP_PUT,
    'bin': "reservations",
    'key': "Amy"
    'val': { 'qty': 19, 'ts': long(time.time()-32 }
  },
]

client.operate(for_event, operations)
client.put(("test", "users", requestor), {'username': requestor})

(key, meta, bins) = client.get(("test","events",for_event))

// Cutoff is 30 seconds ago
cutoff_ts = long(time.time()-30)

for i in range(len(bins["reservations"])):
  res = bins["reservations"][i]
  if res["ts"] < cutoff_ts:
    operations = [
      {
        'op' : aerospike.OPERATOR_INCR,
        'bin': "qty",
        'val': res['qty']
      },
      {
        'op' : aerospike.OP_MAP_REMOVE_BY_KEY,
        'bin' : "reservation",
        'key': res['who'],
        'return_type': aerospike.MAP_RETURN_VALUE
      }
    ]
 
    client.operate(key, operations, {}, wpolicy)