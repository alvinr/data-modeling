import aerospike
import os

config = { 'hosts': [(os.environ.get("AEROSPIKE_HOST", "127.0.01"), 3000)],
           'policies': { 'key': aerospike.POLICY_KEY_SEND }
}
wpolicy = {'gen': aerospike.POLICY_GEN_EQ}

client = aerospike.client(config).connect()

for_event = "Mens 100m Final"
requestor = "Fred"
requested = 5

client.put(("test", "events", for_event), {'name': for_event, 'qty': 500})
client.put(("test", "users", requestor), {'username': requestor})

// Check availability
(key, meta, record) = client.get(("test","events",for_event))

if record['qty'] >= requested:
  operations = [
    {
      'op' : aerospike.OPERATOR_INCR,
      'bin': "qty",
      'val': requested * -1
    },
    {
      'op' : aerospike.OP_LIST_APPEND,
      'bin' : "sold_to",
      'val' : {'who': requestor, 'qty': requested}
    }
  ]
  client.operate(key, operations, meta, wpolicy)

(key, meta, record) = client.get(("test","events",for_event))
print record
