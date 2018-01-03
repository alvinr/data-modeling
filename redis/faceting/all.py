from redis import StrictRedis
import os
import hashlib
import json

redis = StrictRedis(host=os.environ.get("REDIS_HOST", "localhost"), 
                    port=os.environ.get("REDIS_PORT", 6379),
                    db=0)
redis.flushall()

def create_product(product):
  p = redis.pipeline()
  p.sadd("pre_assembled:" + str(product['pre_assembled']), product['sku'])
  p.sadd("pickup_only:" + str(product['pickup_only']), product['sku'])
  p.sadd("weight_in_kg:" + str(product['weight_in_kg']), product['sku'])
  new_product = dict(product)
  del new_product['sku']
  p.hmset("products:" + product['sku'], new_product)
  p.execute()

def create_products():
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
                  'name': "Rubik's Cube",
                  'pre_assembled': True,
                  'pickup_only': False,
                  'weight_in_kg': 0.25,
                  'category': ["Toy"]
                }
  create_product(wheelbarrow)
  create_product(pump)
  create_product(kite)



def match(*keys):
  m = []
  matches = redis.sinter(keys)
  for sku in matches:
    record = redis.hgetall("products:" + sku)
    m.append(record)
  return m

# Find matches based on two criteria
create_products()

# Find the match
matches = match("pre_assembled:True", "pickup_only:False")
for m in matches:
  print m  

matches = match("pre_assembled:True", "pickup_only:False", "weight_in_kg:0.5")
for m in matches:
  print m

def create_hashed_lookups(lookup_key, products):
  h = hashlib.new("ripemd160")
  h.update(str(lookup_key))
  for sku in products:
    redis.sadd("lookups:" + h.hexdigest(), sku)

def match_hashed(lookup_key):
  m = []
  h = hashlib.new("ripemd160")
  h.update(str(lookup_key))
  matches = redis.smembers("lookups:" + h.hexdigest())
  for sku in matches:
    record = redis.hgetall("products:" + sku)
    m.append(record)
  return m

# Find matches based on hashed criteria
lookup_key={'pickup_only': True, 'pre_assembled': True}
create_hashed_lookups(lookup_key, ["123-ABC-723"] )
# Find the match
matches = match_hashed(lookup_key)
for m in matches:
  print m

