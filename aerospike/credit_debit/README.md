# Debit / Credit Transactions
Debit and Credit transactions are often used in textbooks and teaching materials as examples of why you need multi­statement transactions in an RDBMS. Let's start with a simple JSON schema:

```
accounts:
  { name: "Jane", balance: 500 }
  { name: "Bob", balance: 25}
```

In order to transfer $50 from Jane to Bob, we need to modify both of these records. In an RDBMS, you could create a transaction around both of these statements, to ensure that both statements are either fully executed or rollbacked. In a NoSQL database like Aerospike, operations on a single record are atomic, but there is no support for transactions that span multiple statements.

## State Machines
The reality is that there is a workflow or a state machine to track a complex transaction like a debit & credit. Let’s look at a simplified version:

##TODO ADD STATE MACHINE DIAGRAM

The following are critical as we transition through the state machine:
* Operations are atomic
We must credit or debit the transaction once, and only once.
* Concurrency
Multiple transactions can be processed in parallel affecting the same account.
* Idempotent
In the case of failure, transactions can be applied in a idempotent way; we only want to debit or credit once for the same transaction.

Here's an example of the JSON schema to support the transaction state machine:

```
txs:
  { tx_id: "VXW1DG", 
    from: "Jane", 
    to: "Bob",
    amt: 50,
    state: "Begin",
    ts: 1470687668
  }
```

Each record stored the ```to``` and ```from``` account, along with the amountand timestamp (```ts```). We will also extend the accountsschema to include the transactions that have been processed, keyed by the transaction ID (in this example, "VXW1DG"). We will see how we use this structure later.

```
accounts:
  { name: "Bob",
    balance: 75,
    txs: { {"VXW1DG": {"amt":50, "from":"Jane"} }
  }
  {
    name: "Jane",
    balance: 450,
    txs: { {"VXW1DG": {"amt":50, "to":"Bob"} }
  }
```


## Managing the State Machine
To make managing the state machine a little easier, we have a couple of helper functions that check that the transitions are correct, and update its ```status``` of the transaction. Clearly, this can be made much more sophisticated, but you get the idea:

```python
import aerospike
import os
import time
import random
import string

config = { 'hosts': [(os.environ.get("AEROSPIKE_HOST", "127.0.01"), 3000)],
           'policies': { 'key': aerospike.POLICY_KEY_SEND }
}
wpolicy = {'gen': aerospike.POLICY_GEN_EQ}
mpolicy_create = {'map_write_mode': aerospike.MAP_CREATE_ONLY}

client = aerospike.client(config).connect()

def create_account(user, opening_balance):
  client.put(("test", "accounts", user), {'balance':opening_balance})

def simple_debit_credit(from_account, to_account, amount):
  (key, meta, record) = client.get(("test", "accounts",from_account))
  if record['balance'] >= amount:
    client.increment(("test", "accounts", from_account), "balance", amount * -1, meta, wpolicy)
    client.increment(("test", "accounts", to_account), "balance", amount)

# Part One - Simple Debit & Credit
create_account("Dad", 0)
create_account("Mum", 150)
simple_debit_credit("Mum", "Dad", 100)

# Part Two - Workflow
def transition_state(tx_id, from_state, to_state):
  (key_current, meta_current, record_current) = client.select(("test", "txs", tx_id), ["state"])
  if record_current['state'] == from_state:
    operations = [
      {
        'op' : aerospike.OPERATOR_WRITE,
        'bin': "state",
        'val': to_state,
      },
      {
        'op' : aerospike.OPERATOR_WRITE,
        'bin': "ts",
        'val': long(time.time()),
      },
    ]
    (key_changed, meta_changed, _) = client.operate(key_current, operations, meta_current, wpolicy)
    return (key_changed, meta_changed)
  else:
    return (key_current, meta_current)

def check_valid_transition(tx_id, expected_state, got_state):
  if expected_state != got_state:
    print('{0}: Incorrect state, expected:{1}, got:{2}'.format(tx_id, expected_state, got_state))
    return False
  else:
    return True
```

## Process Credit & Debit

Implementing the state diagram from Figure­1, the basic flow needs to check for available funds and then process the credit and debit, as can be seen in the following Python code:

```python
def process_debit_credit(tx_id):  
  (_, _, record) = client.get(("test", "txs", tx_id))
  if check_valid_transition(tx_id, record['state'], "Begin"):
    # Check if funding available
    (_, is_funded) = check_funding(tx_id, record['from'], record['amt'])
    if is_funded:
      process_debit(tx_id, record['from'], record['to'], record['amt'])
      process_credit(tx_id, record['from'], record['to'], record['amt'])
    else:
      process_insufficient_funds(tx_id)

def check_funding(tx_id, from_account, amt):
  (key, meta, record) = client.select(("test", "accounts", from_account), ["balance"])
  if record['balance'] >= amt:
    transition_state(tx_id, "Begin", "Approved")
    return (meta, True)
  else:
    return (meta, False)

def process_insufficient_funds(tx_id):
  transition_state(tx_id, "Begin", "Insufficient Funds")
  (_, _, record) = client.select(("test", "txs", tx_id), ["from", "amt"])
  print("{0}: Insufficient funds account:'{1}' amount:{2}".format(tx_id, record['from'], record['amt']))
```

The main processing routine is ```process_debit_credit```, which checks if there is an available balance to support the transaction, and then performs the debit and credit. The ```check_funding``` function performs the balance check and then transitions the state machine. Finally we have the function process_insufficient_fundsto deal with the transition of the state machine if funds were not available.

## Process Deb
Both the Debit and Credit have the same processing needs: the transaction needs to apply once, and only once. We do this by maintaining a transaction list on the account, which we can check if the transaction exists before debiting the account. We can achieve this by combining both operators into a single atomic operation:

```python
def process_debit(tx_id, from_account, to_account, amount):
  (_, _, record) = client.select(("test", "txs", tx_id), ["state"])
  if check_valid_transition(tx_id, record['state'], "Approved"):
    # Fund the transaction. Verify that this has not been funded already
    (account_meta, is_funded) = check_funding(tx_id, from_account, amount)
    if not is_funded:
      process_insufficient_funds(tx_id)
    else:      
      transition_state(tx_id, "Approved", "Funding")
      operations = [
        {
          'op' : aerospike.OP_MAP_PUT,
          'bin': "txs",
          'key': tx_id,
          'val': {'amt': amount, 'to': to_account },
          'map_policy': mpolicy_create
        },
        {
          'op' : aerospike.OPERATOR_INCR,
          'bin' : "balance",
          'val' : amount * -1
        },
        {
          'op' : aerospike.OPERATOR_READ,
          'bin' : "balance"
        }
      ]
      #TODO: If the map already exists, then in >= 3.9.1 an exception will be thrown
      (_, _, record) = client.operate(("test", "accounts", from_account), operations, account_meta, wpolicy)
      transition_state(tx_id, "Funding", "Debited")
      print("{0}: Debited from:'{1}', amount:{2}, balance:{3}".format(tx_id, from_account, amount, record['balance']))
```

This function needs to process the Approvedtransaction, but since the approval occurred,
there may have been another transaction processed that affects the available balance, so we need to check for available funds again. If funding is still available, then we:
* Add into the ```txs``` Map the amountand from, keyed by the transaction ID. 
* Decrement the available balance
* Check that we are writing the record we read

If the key is already present in the map, then all of these operations will not be applied. This is achieved through the map_policyelement listed as the last element of the OP_MAP_PUT operation, and defined thus:

```
mpolicy_create = {'map_write_mode': aerospike.MAP_CREATE_ONLY}
```

As we have seen previously, we use the write policy (```wpolicy```) to ensure that the Generation of the record is the same as we read ­ if it's not, then the write operation will fail. This protects from another process or thread applying another transaction between the time this thread reads, and the time it writes, the record.

```
wpolicy = {'gen': aerospike.POLICY_GEN_EQ}
```

We now have a mechanism through which we can ensure the debit is made once and only once. If the debit has been made, we can still safely make the state transition.

## Process Credit
We use exactly the same technique for processing the credit as we did on the debit, ensuring that transaction is not present before we apply the credit. The Python code is here:

```python
def process_credit(tx_id, from_account, to_account, amount):
  (_, _, record) = client.select(("test", "txs", tx_id), ["state"])
  if check_valid_transition(tx_id, record['state'], "Debited"):
    (key, meta, record) = client.get(("test", "accounts", to_account))
    # Apply the credit
    operations = [
      {
        'op' : aerospike.OP_MAP_PUT,
        'bin': "txs",
        'key': tx_id,
        'val': {'amt': amount, 'from': from_account },
        'map_policy': mpolicy_create
      },
      {
        'op' : aerospike.OPERATOR_INCR,
        'bin' : "balance",
        'val' : amount
      },
      {
        'op' : aerospike.OPERATOR_READ,
        'bin' : "balance"
      }
    ]
    #TODO: If the map already exists, then in >= 3.9.1 an exception will be thrown
    (_, _, record) = client.operate(key, operations, meta, wpolicy)
    transition_state(tx_id, "Debited", "Credited")
    print("{0}: Credited to:'{1}', amount:{2}, balance:{3}".format(tx_id, to_account, amount, record['balance']))
```

## Pulling This Together
Let's set up two accounts and try both a valid and an invalid transfer:

```python
def generate_transaction_id():
  return ''.join(random.choice(string.ascii_uppercase + string.digits) \
    for _ in range(6))

def start_debit_credit(from_account, to_account, amount):
  tx_id = generate_transaction_id()
  client.put(("test", "txs", tx_id), 
             {'from': from_account,
              'to': to_account, 
              'amt': amount, 
              'state': "Begin",
              'ts': long(time.time())})
  return tx_id

create_account("Daughter", 0)
create_account("Son", 200)
# Enough funds
my_tx = start_debit_credit("Son", "Daughter", 10)
process_debit_credit(my_tx)
# Not enough funds
my_tx = start_debit_credit("Daughter", "Son", 11)
process_debit_credit(my_tx)
```

The ```start_debit_credit``` function is just used to create the initial transaction entry, using ```generate_transaction_id``` to create the ID. You can see two test calls to test the debit/credit process.

When you run this code, you will see an output similar to this:

```
>>> # Enough funds
... my_tx = start_debit_credit("Son", "Daughter", 10) >>> process_debit_credit(my_tx)
IRFIB7: Debited from:'Son', amount:10, balance:190 IRFIB7: Credited to:'Daughter', amount:10, balance:10 >>>
>>> # Not enough funds
... my_tx = start_debit_credit("Daughter", "Son", 11) >>> process_debit_credit(my_tx)
1N7PLF: Insufficient funds account:'Daughter' amount:11
```

As we have already seen, the size of a record has a finite capacity. In the Activity Stream blog, we talked about how to bucket, or slice, large lists. If we wanted to retain the entire history of the transactions, we would need to consider something similar here. However, if this information is simply being used to process the state machine, then before we transition to the terminal state (in this case "Credited"), we could remove this Map element to complete the process. The choice is yours!

## Summary
Multi­statement transaction often encapsulate complex workflows or state machines. Often, if you take a step back, you may be able to see these patterns and leverage Aerospike's ability to process complex operations on a single record. This can enable sophisticated processing, like a debit/credit transaction to operate correctly.
In the next blog post, we will talk about how to re­parent and deal with bi­directional relationships.
