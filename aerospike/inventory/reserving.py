import aerospike
import os
import time

config = { 'hosts': [(os.environ.get("AEROSPIKE_HOST", "127.0.01"), 3000)],
}
wpolicy = {'gen': aerospike.POLICY_GEN_EQ}

client = aerospike.client(config).connect()

for_event = "Mens 100m Final"
requestor = "Fred"
requested = 5

client.put(("test", "events", for_event), {'name': for_event, 'qty': 500})
client.put(("test", "users", requestor), {'username': requestor})

(key, meta, bins) = client.get(("test","events",for_event))

if bins['qty'] >= requested:

  // Create the reservation and decrement the stock
  operations = [
    {
      'op' : aerospike.OPERATOR_INCR,
      'bin': "qty",
      'val': requested * -1
    },
    {
      'op' : aerospike.OP_MAP_PUT,
      'bin': "reservations",
      'key': requestor,
      'val': { 'qty': requested, 
               'ts': long(time.time()) }
    }
  ]
  
  client.operate(key, operations, {}, wpolicy)

  // Assume some credit card auth happens here

  // Remove the reservation and add the ticket sale
  operations = [
    {
      'op' : aerospike.OPERATOR_INCR,
      'bin': "qty",
      'val': requested * -1
    },
    {
      'op' : aerospike.OP_LIST_APPEND,
      'bin' : "sold_to",
      'val' : { 'who': requestor, 'qty': requested}
    },
    {
      'op' : aerospike.OP_MAP_REMOVE_BY_KEY,
      'bin' : "reservation",
      'key': requestor,
      'return_type': aerospike.MAP_RETURN_VALUE
    }
  ]

  client.operate(key, operations, {}, wpolicy)
