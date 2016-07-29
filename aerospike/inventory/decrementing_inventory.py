import aerospike
import os

config = {'hosts': [(os.environ.get('AEROSPIKE_HOST', '127.0.01'), 3000)],
          'policies': { 'key': aerospike.POLICY_KEY_SEND }
}

client = aerospike.client(config).connect()

for_event = "Mens 100m Final"
requestor = "Fred"
requested = 5

client.put(("test", "events", for_event), {'name': for_event, 'qty': 500})
client.put(("test", "users", requestor), {'username': requestor})

# Simple purchase
(key, meta, record) = client.get(("test", "events", for_event))
purchase = { "event": for_event, 'qty': requested }

client.put(("test", "events", for_event), {'qty': record['qty'] - requested})
client.list_append(("test", "users", requestor), "purchased", purchase)

# Query results
(key, meta, record) = client.get(("test", "events", for_event))
print record