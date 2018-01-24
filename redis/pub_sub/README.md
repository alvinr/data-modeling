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

## Conclusion
As you can see, its easy to setup a Publish/Subscribe system with Redis, and create a simple and scalable way to manage stream and event processing. 
