In this blog post, we will talk about a common modelling pattern called bucketing. Aerospike has a maximum record size ­ not an uncommon restriction in a Database. Through embedding, we can model and store large, complex objects. Ultimately, these are restricted by the maximum record size. So how do you deal with that?

## Activity Streams
Let’s look at a simple, well­known example: an activity stream. This could be a stream of posts from those you are following on Twitter, or a channel in Slack that you subscribed to. Let's start with a basic JSON schema of how we could model this:

```
msg:
    { from: "Joe",
      to: [ "Bob", "Jane" ], 
      sent_ts: 1470074748,
      message: "Something silly...",
    }
```

So how can we achieve a consolidated view, based on one users view of their stream? There are many approaches, but let's limit the discussion to the three basic ones:
* Fan out on read
* Fan out on write
* Fan out on write with bucketing

## Fan Out on Read
For each message, we record who sent the message, along with the recipients. If we now want to show all the messages the user has sent and received, how do we do that? The answer is that it's complicated. Even if we create a secondary index on the recipients (the tofield), we then have to perform a scatter­gather query; this data design causes inefficiencies and will not scale well.

To summarize this pattern:
* One record per message sent
* Multiple recipients stored in an array
* Recipient list has a Secondary Index
* Reading a stream for a user requires finding all messages with a matching recipient
* Requires scatter­gather across a cluster

## Fan Out on Write
So how do we avoid the overhead and complexity of obtaining all the messages to display the stream? We can simply model the stream on the user record, and, each time a user posts, add a copy of the message to each of the recipients’ streams. We are simply denormalizing the message to each recipient.

```
user:
  { name: "Bob", 
    stream: [ { from: "Joe",
                to: ["Bob", "Jane"], 
                sent_ts: 1470074748, 
                msg: "Something silly..."
              }
            ]
  }

To make this example simpler to follow, we will simply add a copy of the message to each recipient. In reality, you may want to store the message text once, then add the primary key of the message to a list of each of the users ­ but that's just an optimization of this basic pattern.

Here's some Python code to show how we could cross­post the message to each of the recipients (and the sender), and then print the stream for a given user:

```python
import aerospike
import os
import time
import math
import hashlib

config = { 'hosts': [(os.environ.get("AEROSPIKE_HOST", "127.0.01"), 3000)],
           'policies': { 'key': aerospike.POLICY_KEY_SEND }
}
wpolicy = {'gen': aerospike.POLICY_GEN_EQ}

client = aerospike.client(config).connect()

# Part Two - Fan out on write
def post_msg_fanout(sent_by, to, msg):
  recipients = to
  recipients.append(sent_by)
  post = {'msg': msg, 'from': sent_by, 'sent_ts': long(time.time())}
  for recipient in recipients:
    client.list_insert(("test", "msgs", recipient), "stream", 0, post)

def get_inbox_fanout(user):
  (key, meta, record) = client.get(("test", "msgs", "Jane"))
  return record['stream']

# Send message
post_msg_fanout("Joe", ["Bob", "Jane"], "Silly message...")
post_msg_fanout("Jane", ["Bob"], "My 1st message...")
# Print the messages for "Jane"
messages = get_inbox_fanout("Jane")
for msg in messages:
  print('{0}>> {1}'.format(msg['from'], msg['msg']))
```

When you run the code, you will see the following output:

```
>>> # Send message
... post_msg_fanout("Joe", ["Bob", "Jane"], "Silly message...")
>>> post_msg_fanout("Jane", ["Bob"], "My 1st message...")
>>> # Print the messages for "Jane"
... messages = get_inbox_fanout("Jane")
>>> for msg in messages:
... print('{0}>>{1}'.format(msg['from'],msg['msg'])) ...
Jane>> My 1st message...
Joe>> Silly message...
```

The ```post_msg_fanout``` function adds the message to the sender streamand to each of the recipients. The ```get_inbox_fanout``` function simply has to query the user’s record to get the stream of activity.

So, to summarize this pattern:
* One copy of the message per recipient
* Reading an inbox requires one Primary Key lookup
* Total messages are limited by the maximum record size

## Fan Out on Write with Bucketing
Since we want to avoid record limits, we want to slice or bucket a set of the messages and encapsulate these within a single record. This could be a message count, time period (e.g., day or week), or other criteria that makes sense for the use case. To summarize:
* Each msgrecord contains an array of messages for the user
* Posting a new message is added onto array of messages for each recipient
* Bucket msgrecord so there’s not too many per record

Let's see how we do that with this Python example:

```python
def create_user(user):
  client.put(("test", "users", user), {'total':0})

def calc_bucket(count):
  # Bucket size is 3, just to make testing easier
  return int(math.floor(count/3)) + 1

def post_msg_bucketing(sent_by, to, msg):
  recipients = to
  recipients.append(sent_by)
  post = {'msg': msg, 'from': sent_by, 'sent_ts': long(time.time())}
  for recipient in recipients:
    (key, meta, record) = client.get(("test", "users", recipient))
    count = record['total'] +1
    client.increment(key, "total", 1, meta, wpolicy)
    # Bucket size is 50 messages
    bucket_key = {'user': recipient, 'seq': calc_bucket(count)}
    h = hashlib.new("ripemd160")
    h.update(str(bucket_key))
    client.list_insert(("test", "msgs", h.hexdigest()), "stream", 0, post)

def get_inbox_bucketing(user):
  messages = []
  (key, meta, record) = client.get(("test", "users", user))
  # Find all the buckets based on the total messages received
  for i in range(calc_bucket(record['total']), 0, -1):
    bucket_key = {'user': user, 'seq': i}
    h = hashlib.new("ripemd160")
    h.update(str(bucket_key))
    (key, meta, record) = client.get(("test", "msgs", h.hexdigest()))
    messages.extend(record['stream'])
  return messages

# Post some messages
create_user("Joe")
create_user("Bob")
create_user("Jane")
post_msg_bucketing("Joe", ["Bob", "Jane"], "Silly message...")
post_msg_bucketing("Jane", ["Joe"], "My 1st message...")
post_msg_bucketing("Jane", ["Joe"], "My 2nd message...")
post_msg_bucketing("Jane", ["Joe"], "My 3rd message...")
# Get a users inbox
messages = get_inbox_bucketing("Jane")
for msg in messages:
  print('{0}>> {1}'.format(msg['from'], msg['msg']))
```

Looking at this code, the function ```calc_bucket``` is used to determine the slice that the message will be placed in. This function could decide on any criteria that suits the use case; however, in this case we are slicing by message count and, to make testing easier, using a size limit of 3.

When we reconstruct the complete stream for the user, we want to directly access all the associated buckets ­ and avoid doing a secondary index scan. We do this by creating a compound key of the user and bucket number (see earlier blog post on compound keys). Using a hash function (RIPEMD­160 in this case), we get a consistent key, which we use as the primary key for the bucket. New messages are added to the front of the stream list, by using ```list_insert``` and an index position of zero, i.e., the head of the list.

When the inbox is reassembled in the ```get_inbox_bucketing``` function, we iterate from the most recent bucket backwards, so that the messages list is constructed in reverse chronological order. This is how most user would want to see the information ­ most recent first. In a typical web page, the full history is not presented at first; the user is typically asked to paginate through the stream, so the buckets could be retrieved one by one as needed.

Running the code, you will see the following output:
```
>>> # Post some messages ... create_user("Joe")
>>> create_user("Bob")
>>> create_user("Jane")
>>> post_msg_bucketing("Joe", ["Bob", "Jane"], "Silly message...")
>>> post_msg_bucketing("Jane", ["Joe"], "My 1st message...")
>>> post_msg_bucketing("Jane", ["Joe"], "My 2nd message...")
>>> post_msg_bucketing("Jane", ["Joe"], "My 3rd message...")
>>> # Get a users inbox
... messages = get_inbox_bucketing("Jane")
>>> for msg in messages:
... print('{0}>>{1}'.format(msg['from'],msg['msg'])) ...
Jane>> My 3rd message...
Jane>> My 2nd message...
Jane>> My 1st message...
Joe>> Silly message...
```

To summarize this pattern:
* One copy of the message per recipient
* The message stream is segment or bucketed by a criteria
* Bucketing criteria are used as part of a compound key
* Reading an inbox requires several Primary Key lookups

## Summary
As we can see, the bucketing principle can be applied to many domains and use cases when you need to deal with a long history that will not fit into a single record. Whether you slice by data size, volume, date or some other criteria ­ this pattern can assist in time­series, streams, and many use cases.
In the next blog post, we will talk about the classic RDBMS problem of a debit/credit transaction.