import aerospike
import os

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

client.put(("test", "lookups", "pre_assembled/True"), 
           { 'products': [ "123-ABC-723", "737-DEF-911"] })
client.put(("test", "lookups", "store_pickup_only/True"), 
           { 'products': [ "123-ABC-723"] })

(key1, meta1, record1) = client.get(("test","lookups","pre_assembled/True"))
(key2, meta2, record2) = client.get(("test","lookups","store_pickup_only/True"))

matchs = list(set(record1['products']) & set(record2['products']))

for product in matchs:
  (key, meta, record) = client.get(("test", "products", product))
  print record


