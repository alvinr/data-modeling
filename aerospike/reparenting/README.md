# Re­Parenting, Bi­Directional and Many­-To-­Many Associations

As we discussed in the first article, encapsulation provides a simple mechanism for storage of a directed relationship. But we also saw that bi­directional associations are very common ­ especially coming from an RDBMS and the use of intersection tables ­ whether they are needed or not. So the problem is how to deal with the bi­directionality in a key­value store.

## Parts Management
Let's assume we have a system to track ```parts``` and their ```location```. For example, we have parts available at both our "Warehouse" and "Store" locations. To transfer a part between locations, we need to keep track of the partsavailable at the location, and where any given part is currently located. In JSON, the schema could look like this:

```
locations:
  { name: "Mountain View", type: "Store", parts: [] }
  { name: "las Vegas", type: "Warehouse", parts: { 8BQWQM: {} }


parts:
  { serial_num: "8BQWQM", location: "Las Vegas" }
```

So to move a part between locations, we need to effectively manage the links on both ends of the relationship, as follows:
* Modify the locationon the partsrecord to "Mountain View"
* Add the partinto the list of partsfor the "Mountain View" location
* Remove the partfrom the partslist of the "Las Vegas" location

But these are three separate records, and Aerospike does not support multi­statement transaction. How do we do that, then?

## Tracking Changes to Relationship Ends
In effect, updating both ends of the relationship is a state management problem. We need to guarantee that the change is applied to each once at a minimum. We can safely re­apply this multiple times, but we must ensure it happens at least once. Given that we cannot control this via a transaction, we have to accept that these is an eventual consistency problem we may have to deal with. It's possible that after one end if modified,another process or thread reads the value in the other end. We will deal with that in another blog post.
Looking at the matter in hand, we need to manage how we process the updates to both ends.

## Basic Setup
Below are some helpers that setup the locationsand partsavailable:

```python
import aerospike
import os
import hashlib
import random
import string
import time
import copy

config = {'hosts': [(os.environ.get('AEROSPIKE_HOST', '127.0.01'), 3000)],
          'policies': { 'key': aerospike.POLICY_KEY_SEND }
}
wpolicy = {'gen': aerospike.POLICY_GEN_EQ, 'key': aerospike.POLICY_KEY_SEND}
mpolicy_create = { 'map_write_mode': aerospike.MAP_CREATE_ONLY }

client = aerospike.client(config).connect()

# Moving parts
def generate_xfer():
  return ''.join(random.choice(string.ascii_uppercase + string.digits) \
    for _ in range(6))

def create_location(name, type, part):
  operations = [
    {
      'op' : aerospike.OPERATOR_WRITE,
      'bin': "type",
      'val': type
    },
    {
      'op' : aerospike.OP_MAP_PUT,
      'bin': "parts",
      'key': part,
      'val': {}
    }
  ]
  client.operate(("test", "locations", name), operations, {}, wpolicy)

def create_part(part, location):
  client.put(("test", "parts", part), {'location': location}, {}, wpolicy)
```

You can see that we store the parts available at each location in a Map structure. We will explain why a little later. Since the part can only be at a single location, the the other end of the association can be stored as a scalar value.

## Transfer Process
We will track the status of each of the relationship moves with a xferrecord. We can model a very simple state machine (Figure­1), which can be used to manage the changes to an end of a relationship:

###TODO add diagram

The code to manage the state machine is as follows:

```python
def start_transfer(part, from_loc, to_loc):
  xfer = generate_xfer()
  client.put( ("test", "xfers", xfer),
              { 'status': "Started",
                'xfer_out': "Ready",
                'xfer_in': "Ready",
                'from_loc': from_loc,
                'to_loc': to_loc,
                'part': part, 
                'ts': long(time.time())},
              {}, wpolicy)
  return xfer

def add_transfer_requests(xfer):
  (key, meta, record) = client.get(("test", "xfers", xfer))
  if record['xfer_out'] == "Ready":
    client.map_put( ("test", "locations", record['from_loc']),
                    "xfers",
                    xfer,
                    { 'part': record['part'],
                      'to_loc': record['to_loc'],
                      'xfer_in': "",
                      'xfer_out': "Requested"},
                    {},
                    wpolicy)
  if record['xfer_in'] == "Ready":
    in_rec = copy.copy(record)
    in_rec['xfer_in'] = "Requested"
    client.map_put( ("test", "locations", record['to_loc']),
                     "xfers",
                    xfer,
                    { 'part': record['part'],
                      'from_loc': record['from_loc'],
                      'xfer_in': "Requested",
                      'xfer_out': ""},
                    {},
                    wpolicy)
```

The ````add_transfer_requests``` function adds an entry to the Map structure ```xfers``` on each ```location``` record. This will be used later to coordinate the movement of the relationship end between each of the ```location``` records.

## Modifying the Relationships at Each End
The ```location``` record now has a map of required transfers. Each ```process_xfer_out/in```  function is now responsible for checking the status, and then manipulating the Maps on the end it's responsible for.

```python
def process_xfer_out(location):
  (key, meta, record) = client.get(("test", "locations", location))
  for xfer_key in record['xfers']:
    xfer = record['xfers'][xfer_key]
    if xfer['xfer_out'] == "Requested":
      # Move the part out
        operations = [
          {
            'op' : aerospike.OP_MAP_REMOVE_BY_KEY,
            'bin': "xfers",
            'key': xfer_key,
            'return_type': aerospike.MAP_RETURN_NONE
          },
          {
            'op' : aerospike.OP_MAP_REMOVE_BY_KEY,
            'bin': "parts",
            'key': xfer['part'],
            'return_type': aerospike.MAP_RETURN_NONE
          }
        ]
        (key, meta, record) = client.operate(key, operations, meta, wpolicy)
        # Update the xfer record  
        client.put(("test", "xfers", xfer_key), {'xfer_out': "Done"}, {}, wpolicy)

def process_xfer_in(location):
  (key, meta, record) = client.get(("test", "locations", location))
  for xfer_key in record['xfers']:
    xfer = record['xfers'][xfer_key]
    if xfer['xfer_in'] == "Requested":
      # Move the part in
        operations = [
          {
            'op' : aerospike.OP_MAP_REMOVE_BY_KEY,
            'bin': "xfers",
            'key': xfer_key,
            'return_type': aerospike.MAP_RETURN_NONE
          },
          {
            'op' : aerospike.OP_MAP_PUT,
            'bin': "parts",
            'key': xfer['part'],
            'val': {}
          }
        ]
        (key, meta, record) = client.operate(key, operations, meta, wpolicy)
        # Update the xfer record
        client.put(("test", "xfers", xfer_key), {'xfer_in': "Done"}, {}, wpolicy)
```

Finally, the function ```complete_xfer``` checks that both ```location``` records have been updated before it moves the relationship end of the ```parts``` record.

```python
def complete_xfer(xfer):
  (xfer_key, xfer_meta, xfer_record) = client.get(("test", "xfers", xfer))
  if ( xfer_record['xfer_in'] == "Done" and 
       xfer_record['xfer_out'] == "Done" and
       xfer_record['status'] != 'Finished' ):
    (part_key, part_meta, part_record) = client.get(("test", "parts", xfer_record['part']))
    client.put(part_key, {'location': xfer_record['to_loc']}, part_meta, wpolicy)
    client.put(xfer_key, {'status': "Finished"}, xfer_meta, wpolicy)
```

## Putting This Together
Wrapping these functions together, let's now move our part for "Las Vegas" to "Mountain View":

```python
# Create parts & locations
part = "8BQWQM"
from_loc = "Las Vegas"
to_loc = "Mountain View"

create_location(from_loc, "Warehouse", part)
create_location(to_loc, "Store", "ABC123")
create_part(part, from_loc)
# transfer_part
xfer = start_transfer(part, from_loc, to_loc)
add_transfer_requests(xfer)
process_xfer_out(from_loc)
process_xfer_in(to_loc)
complete_xfer(xfer)

# Print the results
(_, _, record) = client.get(("test", "locations", from_loc))
print record
(_, _, record) = client.get(("test", "locations", to_loc))
print record
(_, _, record) = client.get(("test", "parts", part))
print record
(_, _, record) = client.get(("test", "xfers", xfer))
print record

```

If you run the code, you will see the following output:

```
>>> # Print the results
... (_, _, record) = client.get(("test", "locations", from_loc))
>>> print record
{'parts': {}, 'type': 'Warehouse', 'xfers': {}}
>>> (_, _, record) = client.get(("test", "locations", to_loc))
>>> print record
{'parts': {'ABC123': {}, '8BQWQM': {}}, 'type': 'Store', 'xfers': {}} >>> (_, _, record) = client.get(("test", "parts", part))
>>> print record
{'location': 'Mountain View'}
>>> (_, _, record) = client.get(("test", "xfers", xfer))
>>> print record
{'status': 'Finished', 'xfer_in': 'Done', 'ts': 1470934675, 'part': '8BQWQM', 'xfer_out': 'Done', 'to_loc': 'Mountain View', 'from_loc': 'Las Vegas'}
```

## Many­-To-­Many Associations
In this example, we have been dealing with one­-to-­many associations: the partis in one and only one ```location```, and the ```location``` may have zero or more parts. Many­-to-­many associations are usually resolved with an intersection class or entity. Back in the first blog post, where we talked about assignments of people to departments, the assignmentswas essentially the intersection between employeesand departments, because over time, a person could work for many departments (see Figure­2).

### TODO insert diagram

If an employee changes departments, how can we deal with that request?
* Create a new Assignment
* Modify the existing Assignment

If we create a new assignment, then we can retain a history of all the Departments the Employee has worked for. But perhaps we don't want that history, and we are only concerned with the current assignment. There are many ways to deal with this requirement, but we chose to simply modify the associations between the three classes or entities.

There are four relationship ends that may need to be moved: both ends of the Department and Assignment association, and both ends of the Employee and Assignment association. The patterns described above can easily be adapted to now manage all of the association modifications is a robust and reliable way.

## Summary
Dealing with bi­directional & many­to­many relationships has some complexity, because you have multiple records to update. Firstly, you should ask yourself if this relationship needs to be bidirectional; if not, you can simply use the technique of encapsulation to store a directed relationship. If you need to have a bidirectional relationship, then you need a mechanism, like described above, to manage the transfer of each of the ends. This needs to ensure that each end is moved at least once, and can be reprocessed in a safe and consistent way in the event of a crash. Because multiple writes (and thus transactions) are used, the changes are eventually consistent. You need to take heed, as this could adversely affect the logic of your application code.



