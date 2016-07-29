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
                'qty': 495, 
                'sold_to': [ {'who': 'Fred', 'qty': 5} ],
                'pending': [ {'who': 'Fred', 'qty': 5} ]
              }

client.put(("test", "events", for_event), reservation)
client.put(("test", "users", requestor), {'username': requestor})

# Posting
(key, meta, record) = client.get(("test","events",for_event))

for res in record["pending"]:
  # Add to users record
  client.list_append(("test","users", res['who']), "purchases", {'event': for_event, 'qty': res['qty']})
  client.list_pop(("test","events", for_event), "pending", 0, meta, wpolicy)

# Query results
(key, meta, record) = client.get(("test", "events", for_event))
print record
(key, meta, record) = client.get(("test", "users", requestor))
print record
