import aerospike
import os
import hashlib

config = { 'hosts': [(os.environ.get("AEROSPIKE_HOST", "127.0.01"), 3000)],
           'policies': { 'key': aerospike.POLICY_KEY_SEND }
}
wpolicy = {'gen': aerospike.POLICY_GEN_EQ}

client = aerospike.client(config).connect()

def create_account(user, opening_balance):
  client.put(("test", "accounts", user), {'balance':opening_balance})

def simple_debit_credit(from_account, to_account, amount):
  (key, meta, record) = client.get(("test", "accounts",from_account))
  if record['balance'] >= amount:
    client.increment(("test", "accounts",from_account), "balance", amount * -1, meta, wpolicy)
    client.increment(("test", "accounts",to_account), "balance", amount)

# Part One - Simple Debit & Credit
create_account("Dad", 0)
create_account("Mum", 200)
simple_debit_credit("Mum", "Dad", 100)

# Part Two - Transaction Boundary
def generate_transaction_id():
  return ''.join(random.choice(string.ascii_uppercase + string.digits) \
    for _ in range(6))

def safe_debit_credit(from_account, to_account, amount):
  tx_id = generate_transaction_id()
  client.put(("test", "tx", tx_id), 
             {'from': from_account, 'to': to_account, 'amt': amount, 'state': "Pending"})
  return tx_id

def process_debit_credit(tx_id):  
  (key, meta, record) = client.get(("test", "tx", tx_id))
  if record['state'] == "Pending":
    # Perform the Debit
    client.increment(("test", "accounts", record['from']), "balance", record['amt'] * -1)

  operations = [
    {
      'op' : aerospike.OPERATOR_INCREMENT,
      'bin': "balance",
      'val': amount * -1
    },
    {
      'op' : aerospike.OP_LIST_APPEND,
      'bin' : "pending",
      'val' : {'to': to_account, 'amount': amount, 'ts': 0}
    }
  ]
  client.operate(key, operations, meta, wpolicy)


create_account("Daughter", 0)
create_account("Son", 200)
my_tx = safe_debit_credit("Son", "Daughter", 7)
while process_debit_credit(my_tx) not in ["Succeded"]


