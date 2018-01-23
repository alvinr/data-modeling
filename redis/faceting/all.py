from redis import StrictRedis
import os
import hashlib
import json

redis = StrictRedis(host=os.environ.get("REDIS_HOST", "localhost"), 
                    port=os.environ.get("REDIS_PORT", 6379),
                    db=0)
redis.flushall()

def create_event(product):
  p = redis.pipeline()
  p.sadd("reserve_seating:" + str(product['reserve_seating']), product['sku'])
  p.sadd("medal_event:" + str(product['medal_event']), product['sku'])
  p.sadd("venue:" + str(product['venue']), product['sku'])
  p.hmset("products:" + product['sku'], product)
  p.execute()

def create_events():
  m100m_final = { 'sku': "123-ABC-723",
                  'name': "Men's 100m Final",
                  'reserve_seating': True,
                  'medal_event': True,
                  'venue': "Olympic Stadium",
                  'category': ["Track & Field", "Mens"]
                }
  w4x100_heat = { 'sku': "737-DEF-911",
                  'name': "Women's 4x100m Heats",
                  'reserve_seating': True,
                  'medal_event': False,
                  'venue': "Olympic Stadium",
                  'category': ["Track & Field", "Womens"]
                }
  wjudo_qual =  { 'sku': "320-GHI-921",
                  'name': "Womens Judo Qualifying",
                  'reserve_seating': False,
                  'medal_event': False,
                  'venue': "Nippon Budokan",
                  'category': ["Martial Arts", "Womens"]
                }
  create_event(m100m_final)
  create_event(w4x100_heat)
  create_event(wjudo_qual)

def match(*keys):
  m = []
  matches = redis.sinter(keys)
  for sku in matches:
    record = redis.hgetall("products:" + sku)
    m.append(record)
  return m

# Find matches based on two criteria
create_events()

# Find the match
matches = match("reserve_seating:True", "medal_event:False")
for m in matches:
  print m  

matches = match("reserve_seating:True", "medal_event:False", "venue:Olympic Stadium")
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
lookup_key={'reserve_seating': True, 'medal_event': True}
create_hashed_lookups(lookup_key, ["123-ABC-723"] )
# Find the match
matches = match_hashed(lookup_key)
for m in matches:
  print m

