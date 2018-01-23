# Faceted Queries
Faceting is a pattern that can be applied to many domain problems. Let's stick with a really obvious problem: you have a product catalog that you need to query on a distinct set of attributes. We will use the events of the 2020 Olympic games as the products we we want search. Let's start with a schema in JSON:

```
products:
  { 'sku': "737-DEF-911",
    'name': "Women's 4x100m Heats",
    'reserve_seating': True,
    'medal_event': False,
    'venue': "Olympic Stadium",
    'category': ["Track & Field", "Womens"]
  }
```

Let's assume that SKU (Stock Keeping Unit) is the Primary Key. If we know the Primary Key, then we get a direct lookup in order to get the record. But how many of us remember the SKU of any product we want to buy? You are likely to want to find the product through some other criteria, like its name, or whether it's in a particular product category.

## The RDBMS Solution
In an RDBMS, you may be tempted to create secondary indexes on any attribute you may want to query on ­- for example, name, ```venue``` etc. Creating multiple indexes means that as the record is inserted, multiple indexes have to be changed; updates to those indexed values will also require index updates. A list like category would need to be implemented as an intersection table between the unique Categories and the usage by the Product. Then you’ll certainly end up with multiple tables, joins and potential index merges to effectively query on multiple criteria. As the index structures are maintained, this can impact the concurrency, latencies, and throughput of the overall system. When you then distribute this data across many machines ­- for example, using Partitioning ­- you’ll need to scatter the query across each of these nodes and gather all the results together. Again, this can impact the latency of the results back to the client.

## Faceting
Faceting is just simply turning each of these possible secondary index queries into a multiple key lookups. So let's look at a possible JSON schema:

```
products:
  { 'sku': "123-ABC-723", 'name': "Men's 100m Final", 'reserve_seating': True, 'medal_event': True, 'venue': "Olympic Stadium", 'category': ["Track & Field", "Mens"] }
  { 'sku': "737-DEF-911", 'name': "Women's 4x100m Heats", 'reserve_seating': True, 'medal_event': False, 'venue': "Olympic Stadium", 'category': ["Track & Field", "Womens"] }
  { 'sku': "320-GHI-921", 'name': "Womens Judo Qualifying", 'reserve_seating': False, 'medal_event': False, 'venue': "Nippon Budokan", 'category': ["Martial Arts", "Womens"]
                }
lookups:
  { key: "reserve_seating/True", products: [ "123-ABC-723", "737-DEF-911" ] }
  { key: "venue/Nippon Budokan", products: [ "320-GHI-921" ] }
  { key: "venue/Olympic Stadium", products: [ "123-ABC-723", "737-DEF-911" ] }
  { key: "medal_event/False", products: [ "320-GHI-921" ] }
```

So if we are looking for a product in the venue of "Nippon Budokan", we can perform a Key query on ```lookups``` with the value "venue/Nippon Budokan". This returns a record with an encapsulated set of product SKUs. We can then iterate through the ```products``` list and perform Primary Key lookups for each product.
Thus, we can now avoid performing a scatter & gather across a distributed system and turn this into a series of Primary Key lookups, each of which can be parallelized. This dramatically improves the throughput, latency, and concurrency of the system. It also has the nice side effect that it will be fastest way to return the first record ­- whichever server returns responds the fastest, the record can be delivered for processing by the application.
The final benefit of this pattern is that you no longer need to build and maintain indexes on each of the attributes. Building a new lookup simply requires creating and inserting a new lookup record. When the attributes of the ```product``` change, then there is a secondary process to manage the associated lookup records, so this is not for free. The balance is between the need for speedy and flexible lookups versus the cost of maintenance. If the values are slowly changing or immutable, then it may be a good trade off.

## Multiple Attribute Faceting
But what about filtering on multiple attributes? This is a typical query, so taking our example again, what if we wanted to find products where ```medal_event`` and ```reserve_seating``` are both True?

There are a couple of ways to achieve this. First lets find the intersection of the two lists. Here's an example of doing that in Python:

```python
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
```

We use the [```sinter```](https://redis.io/commands/sinter) function to find the intersection of all the supplied keys, which is a set so can be any number of query criteria. This is a simple and effect way to search for the criteria, running the code you will see the following:

```
>>> matches = match("reserve_seating:True", "medal_event:False")
>>> for m in matches:
...   print m  
... 
{'sku': '737-DEF-911', 'category': "['Track & Field', 'Womens']", 'name': "Women's 4x100m Heats", 'venue': 'Olympic Stadium', 'medal_event': 'False', 'reserve_seating': 'True'}
```

This is a reasonable solution, ```sinter``` is ```O(N * M)``` in terms of time complexity, where N is cardinality of the smallest set and M is the number of matching keys.

So how can we reduce the complexity when the faced with larges set or large number of keys to check?

## Compounding and Hashing Attribute Keys
In effect, what we are doing is creating a compound key. This is something that you could build in a RDBMS ­- along with the previously discussed overhead. The pattern is similar with Redis; in essence, we build a compound key from the attributes we want to query, but we use this to create a Primary Key for the object we want to lookup. Here's a sample of what that data in JSON form:

```json
lookups:
  { key: {'reserve_seating': True, 'medal_event': True},
    products: [ "123-ABC-723"]
  }
```

Here's a piece of Python code to perform the compound query:

```python
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
```

The function ```create_hased_lookups``` is creating a hash (using [RIPEMD­160](https://en.wikipedia.org/wiki/RIPEMD) hash - a collision free hashing algorithm used by Bitcoin and others) of the compound values we want to query for, thus providing a compact and reproducible value to query against. We want to deterministic hash that minimizes collision, RIPEMD­160 is used in the Bitcoin algorithm, but we could have used SHA512 or any other popular hash. We could have used a simple concatenation of strings, but a hash avoids the problem of key size and key distribution. This allows a Primary Key lookup to be made on these compound values. Once the ```lookup``` record has been returned, we can they execute the subsequent Primary Key lookups of the ```product``` data as we have done previously.

Running the code, you will see the matching product printed:

```
{ 'sku': '737-DEF-911',
  'category': "['Track & Field', 'Womens']", 
  'name': "Women's 4x100m Heats", 
  'venue': 'Olympic Stadium', 
  'medal_event': 'False', '
  reserve_seating': 'True'
}
```

## Summary
As can be seen, faceting is a powerful pattern that enables complex query patterns to executed in an efficient way with a key­-value store. With any denormalization, there is always the cost of propagating the changes to the denormalized data. The trade-off is always the frequency of changes versus the query flexibility that your application needs.
In the next article, we will discuss how to model queues and state machines [queues and state machines](../state_machines/README.md).