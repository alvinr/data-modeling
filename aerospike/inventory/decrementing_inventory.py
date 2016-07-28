import aerospike
import os

config = {'hosts': [(os.environ.get('AEROSPIKE_HOST', '127.0.01'), 3000)]}

client = aerospike.client(config).connect()

for_event = "Mens 100m Final"
requestor = "Fred"
requested = 5

client.put(("test", "events", for_event), {'name': for_event, 'qty': 500})
client.put(("test", "users", requestor), {'username': requestor})

purchase = { "event": for_event, 'qty': requested }

client.increment(("test", "events", for_event), 'qty', requested * -1)
client.list_append(("test", "users", requestor), "purchased", purchase)