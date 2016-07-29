import aerospike
import os
import hashlib

config = { 'hosts': [(os.environ.get("AEROSPIKE_HOST", "127.0.01"), 3000)],
           'policies': { 'key': aerospike.POLICY_KEY_SEND }
}

client = aerospike.client(config).connect()

wheelbarrow = { 'sku': "123-ABC-723",
                'name': "Wheelbarrow",
                'pre_assembled': True,
                'pickup_only': True,
                'weight_in_kg': 12,
                'category': ["Garden", "Tool"]
              }

pump =        { 'sku': "737-DEF-911",
                'name': "Bicycle Pump",
                'pre_assembled': True,
                'pickup_only': False,
                'weight_in_kg': 0.5,
                'category': ["Tool"]
              }

kite =        { 'sku': "320-GHI-921",
                'name': "Kite",
                'pre_assembled': False,
                'pickup_only': False,
                'weight_in_kg': 0.5,
                'category': ["Toy"]
              }

client.put(("test", "products", wheelbarrow['sku']), wheelbarrow)
client.put(("test", "products", pump['sku']), pump)
client.put(("test", "products", kite['sku']), kite)


lookup_key=[{'pickup_only': True}, {'pre_assembled': True} ]
h = hashlib.new("ripemd160")
h.update(str(lookup_key))

client.put(("test", "lookups", h.hexdigest()), 
           { 'products': [ "123-ABC-723"] })

(key, meta, found) = client.get(("test", "lookups", h.hexdigest()))

for product in found['products']:
  (key, meta, record) = client.get(("test", "products", product))
  print record




