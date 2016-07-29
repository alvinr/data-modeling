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

client.put(("test", "events", for_event), {'name': for_event, 'qty': 500})
client.put(("test", "users", requestor), {'username': requestor})

# Reserve stock
(key, meta, record) = client.get(("test","events",for_event))

if record['qty'] >= requested:
  # Create the reservation and decrement the stock
  operations = [
    {
      'op' : aerospike.OPERATOR_WRITE,
      'bin': "qty",
      'val': record['qty'] - requested
    },
    {
      'op' : aerospike.OP_MAP_PUT,
      'bin': "reservations",
      'key': requestor,
      'val': { 'qty': requested, 'ts': long(time.time()) }
    }
  ]  
  (key, meta, record) = client.operate(key, operations, meta, wpolicy)
  # Assume some credit card auth happens here
  # Remove the reservation and add the ticket sale
  operations = [
    {
      'op' : aerospike.OP_LIST_APPEND,
      'bin' : "sold_to",
      'val' : { 'who': requestor, 'qty': requested}
    },
    {
      'op' : aerospike.OP_MAP_REMOVE_BY_KEY,
      'bin' : "reservations",
      'key': requestor,
      'return_type': aerospike.MAP_RETURN_VALUE
    },
    {
      'op' : aerospike.OP_LIST_APPEND,
      'bin' : "pending",
      'val' : { 'who': requestor, 'qty': requested}
    }
  ]
  client.operate(key, operations, meta, wpolicy)

# Query results
(key, meta, record) = client.get(("test", "events", for_event))
print record
