# Publish / Subscribe
Redis provides a simple mechanism to broadcast events. These events can have many subscribers who can then process the each event as they occur.

## Purchasing metrics
Going back to our Olympics 2020 application, Sales and marketing has requested a number of metrics to be collected during the purchase workflow. Unsurprisingly, they have come back with a new set of metrics they want to collect. If we take a look at how we did thie previously

```python
def post_purchases(event_name):
...
    p.hincrbyfloat("sales_summary", event_name + ":total_sales", order['cost'])
    p.hincrby("sales_summary", event_name + ":total_tickets_sold", order['qty'])
    hour_of_day = int(time.strftime("%H"))
    vals = ["INCRBY", "u8", (hour_of_day+1) * 8, order['qty']]
    p.execute_command("BITFIELD", "sales_histogram:time_of_day", *vals)
    p.execute_command("BITFIELD", "sales_histogram:time_of_day:" + event_name, *vals)
    p.execute()
```

We basically put all the metric collection logic in the ```post_purchases``` function. This was convenient, but now it means we have to change this function each time we want to make changes. We are refactor this so that ```post_purchases``` simply stored the details of the order and creates an event for the new purchase order creation.

```python
def post_purchases(order_id, purchase):
	redis.hmset("purchase_order_details:" + order_id, purchase)
	redis.publish("purchase_orders", order_id) 
```

This simplifies the ```post_purchase``` function to storing the purchase order and publishing the Order Id to the ```purchase_orders``` stream.

## One writer, many readers
Now that we have the event posted, we can now simply create as many readers as required, to consume the event and process as needed.

```python
def listener_sales_analytics(queue):
	l = redis.pubsub(ignore_subscribe_messages=True)
	l.subscribe(queue)
	p = redis.pipeline()
	for message in l.listen():
		order_id = message['data']
		order = redis.hgetall("purchase_order_details:" + order_id)
		hour_of_day = int(time.strftime("%H", time.gmtime(long(order['ts']))))
		vals = ["INCRBY", "u8", (hour_of_day+1) * 8, order['qty']]
		p.execute_command("BITFIELD", "sales_histogram:time_of_day", *vals)
		p.execute_command("BITFIELD", "sales_histogram:time_of_day:" + order['event'], *vals)
		p.execute()

def listener_events_analytics(queue):
	l = redis.pubsub(ignore_subscribe_messages=True)
	l.subscribe(queue)
	p = redis.pipeline()
	for message in l.listen():
		order_id = message['data']
		order = redis.hgetall("purchase_order_details:" + order_id)
		event_name = order['event']
		p.sadd("sales:" + event_name, order_id)
		p.hincrbyfloat("sales_summary", event_name + ":total_sales", order['cost'])
		p.hincrby("sales_summary", event_name + ":total_tickets_sold", order['qty'])
		p.execute()

def listener_customer_purchases(queue):
	l = redis.pubsub(ignore_subscribe_messages=True)
	l.subscribe(queue)
	p = redis.pipeline()
	for message in l.listen():
		order_id = message['data']
		order = redis.hgetall("purchase_order_details:" + order_id)
		p.sadd("invoices:" + order['who'], order_id)
		p.execute()
```
Each of these functions can now use the event and process it in whatever way they see fit. But this also means that as the requirements change (you know those Sales and Marketing people), that we can just add more subscribers to perform further processing.

In the functions above, the ```listen``` method is used, all this is doing is blocking until an event is published. While this is Python specific, language dependent alternatives exist.

## Pattern specific subscriptions
You do not have to subscribe to all messages, you can supply a glob style wildcard. Lets modify the ```post_purchase``` function so that we also publish the event the purchase was for.

```python
def post_purchases(order_id, purchase):
	redis.hmset("purchase_order_details:" + order_id, purchase)
	redis.publish("purchase_orders", order_id) 
	redis.publish("purchase_orders:" + purchase['event'], order_id) 
```

We have added the last line, so that we include the event name in the key name. This allows us to create a subscription for all or just some of the events. Lets say we have one process that wants to see all the Events and one that just wants to see "Opening Ceremony" sales.

```python
def listener_openening_ceremony_alerter(queue):
	l = redis.pubsub(ignore_subscribe_messages=True)
	l.subscribe(queue + ":Opening Ceremony")
	p = redis.pipeline()
	for message in l.listen():
		order_id = message['data']
		order = redis.hgetall("purchase_order_details:" + order_id)
		print "===> Purchase {}: #{} ${}".format(order['event'], order['qty'], order['cost'])

def listener_ceremony_alerter(queue):
	l = redis.pubsub(ignore_subscribe_messages=True)
	l.psubscribe(queue + ":* Ceremony")
	p = redis.pipeline()
	for message in l.listen():
		order_id = message['data']
		order = redis.hgetall("purchase_order_details:" + order_id)
		print "Purchase {}: #{} ${}".format(order['event'], order['qty'], order['cost'])

```

As you can see in the function ```listener_ceremony_alerter``` of you can see that we use the [PSUBSCRIBE](https://redis.io/commands/psubscribe) operation. This allows us to use a wildcard matching pattern, in this case to include any purchase that includes the phrase "Ceremony". If we have code to invoke these:

```python
threads_2 = []
threads_2.append(threading.Thread(target=listener_openening_ceremony_alerter, args=("purchase_orders",)))
threads_2.append(threading.Thread(target=listener_ceremony_alerter, args=("purchase_orders",)))

for i in range(len(threads_2)):
	threads_2[i].setDaemon(True)
	threads_2[i].start()

events = ["Womens Judo", "Mens 4x400", "Opening Ceremony", "Closing Ceremony"]
for e in events:
	create_event(e)

for i in range(50):
	purchase(events[random.randrange(0, len(events))])
	time.sleep(random.random())
```

When we run, we can see the following:

```
Purchase Closing Ceremony: #6 $120
Purchase Closing Ceremony: #8 $160
Purchase Closing Ceremony: #3 $60
Purchase Opening Ceremony: #1 $20
===> Purchase Opening Ceremony: #1 $20
===> Purchase Opening Ceremony: #1 $20
 Purchase Opening Ceremony: #1 $20
```

Notice that both listeners receive and act on the event, so make sure that you take in account how wild card subscriptions work.

## Conclusion
You have see that you can
* Create a publisher
* Have many subscribers receive the message
* Have subscribers use wildcards to filter the message they receive

As you can see, its easy to setup a Publish/Subscribe system with Redis, and create a simple and scalable way to manage stream and event processing. 
