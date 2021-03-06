# Faceted Queries
Faceting is a pattern that can be applied to many domain problems. Let's stick with a really obvious problem: you have a product catalog that you need to query on a distinct set of attributes. Let's start with a schema in JSON:

```
products:
  { sku: "123-ABC-723",
    name: "Wheelbarrow",
    pre_assembled: True,
    weight_in_kg: 12,
    category: ["Garden", "Tool"]
  }
```

Let's assume that SKU (Stock Keeping Unit) is the Primary Key. If we know the Primary Key, then we get a direct lookup in order to get the record. But how many of us remember the SKU of any product we want to buy? You are likely to want to find the product through some other criteria, like its name, or whether it's in a particular product category.

## The RDBMS Solution
In an RDBMS, you may be tempted to create secondary indexes on any attribute you may want to query on ­- for example, name, ```weight_in_kg``` etc. Creating multiple indexes means that as the record is inserted, multiple indexes have to be changed; updates to those indexed values will also require index updates. A list like category would need to be implemented as an intersection table between the unique Categories and the usage by the Product. Then you’ll certainly end up with multiple tables, joins and potential index merges to effectively query on multiple criteria. As the index structures are maintained, this can impact the concurrency, latencies, and throughput of the overall system. When you then distribute this data across many machines ­- for example, using Partitioning ­- you’ll need to scatter the query across each of these nodes and gather all the results together. Again, this can impact the latency of the results back to the client.

## Faceting
Faceting is just simply turning each of these possible secondary index queries into a multiple primary key lookups. So let's look at a possible JSON schema:

```
products:
  { sku: "123-ABC-723", name: "Wheelbarrow", pre_assembled: True, pickup_only: True, weight_in_kg: 12, category: ["Garden", "Tool"] }
  { sku: "737-DEF-911", name: "Bicycle Pump", pre_assembled: True, pickup_only: False, weight_in_kg: 0.5, category: ["Tool"] }
  { sku: "320-GHI-921", name: "Kite", pre_assembled: False, pickup_only: False, weight_in_kg: 0.5, category: ["Toy"] }

lookups:
  { key: "category/Tool", products: [ "123-ABC-723", "737-DEF-911" ] }
  { key: "category/Garden", products: [ "123-ABC-723"] }
  { key: "category/Toy", products: [ "320-GHI-921" ] }
  { key: "pre_assembled/True", products: [ "123-ABC-723", "737-DEF-911"] }
```

So if we are looking for a product in the category of "Tool", we can perform a Primary Key query on ```lookups``` with the value "category/Tool". This returns a record with an encapsulated set of product SKUs. We can then iterate through the ```products``` list and perform Primary Key lookups for each product.
Thus, we can now avoid performing a scatter & gather across a distributed system and turn this into a series of Primary Key lookups, each of which can be parallelized. This dramatically improves the throughput, latency, and concurrency of the system. It also has the nice side effect that it will be fastest way to return the first record ­- whichever server returns responds the fastest, the record can be delivered for processing by the application.
The final benefit of this pattern is that you no longer need to build and maintain indexes on each of the attributes. Building a new lookup simply requires creating and inserting a new lookup record. When the attributes of the ```product``` change, then there is a secondary process to manage the associated lookup records, so this is not for free. The balance is between the need for speedy and flexible lookups versus the cost of maintenance. If the values are slowly changing or immutable, then it may be a good trade off.

## Multiple Attribute Faceting
But what about filtering on multiple attributes? This is a typical query, so taking our example again, what if we wanted to find products where ```pickup_only`` and ```pre_assembled``` are both True?

There are a couple of ways to achieve this. We could could perform two queries, and then find the intersection. Here's an example of doing that in Python:

```python
import aerospike
import os
import hashlib

config = { 'hosts': [(os.environ.get("AEROSPIKE_HOST", "127.0.01"), 3000)],
           'policies': { 'key': aerospike.POLICY_KEY_SEND }
}

client = aerospike.client(config).connect()

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
                  'name': "Kite",
                  'pre_assembled': False,
                  'pickup_only': False,
                  'weight_in_kg': 0.5,
                  'category': ["Toy"]
                }
  client.put(("test", "products", wheelbarrow['sku']), wheelbarrow)
  client.put(("test", "products", pump['sku']), pump)
  client.put(("test", "products", kite['sku']), kite)

def create_lookups():
  client.put(("test", "lookups", "pre_assembled/True"), 
             { 'products': [ "123-ABC-723", "737-DEF-911"] })
  client.put(("test", "lookups", "store_pickup_only/True"), 
             { 'products': [ "123-ABC-723"] })

def match(key1, key2):
  m = []
  (key1, meta1, record1) = client.get(("test","lookups",key1))
  (key2, meta2, record2) = client.get(("test","lookups",key2))
  matches = list(set(record1['products']) & set(record2['products']))
  for sku in matches:
    (key, meta, record) = client.get(("test", "products", sku))
    m.append(record)
  return m

## Find matches based on two criteria
create_products()
create_lookups()
# Find the match
matches = match("pre_assembled/True", "store_pickup_only/True")
for m in matches:
  print m  

```

We can use the inbuilt list manipulation built into most languages to find the intersection, see code in bold above. Running the code, you will see the following printed:

```
products:
  { 'sku': '123-ABC-723', 
    'category': ['Garden', 'Tool'], 
    'name': 'Wheelbarrow', 
    'pre_assembled': True, 
    'pickup_only': True, 
    'weight_in_kg': 12
  }
```

While this adds a lot of complexity, as you need to calculate the intersection of the results of each query, it’s still a reasonable, scalable solution. But how can we remove the need to find the intersection in the client code, especially if each of those lists starts to get really big?

## Compounding and Hashing Attribute Keys
In effect, what we are doing is creating a compound key. This is something that you could build in a RDBMS ­- along with the previously discussed overhead. The pattern is similar with Aerospike; in essence, we build a compound key from the attributes we want to query, but we use this to create a Primary Key for the object we want to lookup. Here's a sample of what that data in JSON form:

```json
lookups:
  { key: {pre_assembled: True, pickup_only: True},
    products: [ "123-ABC-723"]
  }
```

Here's a piece of Python code to perform the compound query:

```python
def create_hashed_lookups(lookup_key, products):
  h = hashlib.new("ripemd160")
  h.update(str(lookup_key))
  client.put(("test", "lookups", h.hexdigest()), 
             { 'products': products})

def match_hashed(lookup_key):
  m = []
  h = hashlib.new("ripemd160")
  h.update(str(lookup_key))
  (key, meta, found) = client.get(("test", "lookups", h.hexdigest()))
  for sku in found['products']:
    (key, meta, record) = client.get(("test", "products", sku))
    m.append(record)
  return m

# Find matches based on hashed criteria
lookup_key={'pickup_only': True, 'pre_assembled': True}
create_hashed_lookups(lookup_key, ["123-ABC-723"])
# Find the match
matches = match_hashed(lookup_key)
for m in matches:
  print m

```

The function ```create_hased_lookups``` is creating a hash (using RIPEMD­160) of the compound values we want to query for, thus providing a compact and reproducible value to query against. We want to deterministic hash that minimizes collision, RIPEMD­160 is used in the Bitcoin algorithm, but we could have used SHA512 or any other popular hash. We could have used a simple concatenation of strings, but a hash avoids the problem of key size and key distribution. This allows a Primary Key lookup to be made on these compound values. Once the ```lookup``` record has been returned, we can they execute the subsequent Primary Key lookups of the ```product``` data as we have done previously.

Running the code, you will see the matching product printed:

```
products:
  { 'sku': '123-ABC-723', 
    'category': ['Garden', 'Tool'], 
    'name': 'Wheelbarrow', 
    'pre_assembled': True, 
    'pickup_only': True, 
    'weight_in_kg': 12
  }
```

## Summary
As can be seen, faceting is a powerful pattern that enables complex query patterns to executed in an efficient way with a key­value store. With any denormalization, there is always the cost of propagating the changes to the denormalized data. The tradeoff is always the frequency of changes versus the query flexibility that your application needs.
In the next article, we will discuss how to model queues and state machines [queues and state machines](../state_machines/README.md).