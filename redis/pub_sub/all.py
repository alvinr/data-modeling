from redis import StrictRedis, WatchError
import os
import time
import random
import string
import threading

redis = StrictRedis(host=os.environ.get("REDIS_HOST", "localhost"), 
                    port=os.environ.get("REDIS_PORT", 6379),
                    db=0)
redis.flushall()

def generate_order_id():
  return ''.join(random.choice(string.ascii_uppercase + string.digits) \
    for _ in range(6))

def create_event(event_name):
	redis.hmset("events:" + event_name, {'event': event_name})

def purchase(event):
	qty = random.randrange(1, 10)
	price = 20
	order_id = generate_order_id()
	purchase = { 'who': "Jim", 'qty': qty, 'ts': long(time.time()), 'cost': qty * price, 
               'order_id': order_id, 'event': event_name }
  post_purchases(purchase)

def post_purchases(order_id, purchase):
	redis.hmset("purchase_order_details:" + order_id, purchase)
	redis.publish("purchase_orders", order_id) 

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

def print_statistics():
	while True:	
		print "\n======== {}".format(time.strftime("%a, %d %b %Y %H:%M:%S"))
		for event in redis.scan_iter(match="events:*"):
			(_, event_name) = event.split(":")  
			print "Event: {}".format(event_name)
			print " Total Sales: ${}".format(redis.hget("sales_summary", event_name + ":total_sales"))
			print " Total Tickets Sold: {}".format(redis.hget("sales_summary", event_name + ":total_tickets_sold"))
			hist = redis.get("sales_histogram:time_of_day:" + event_name)
			print " Histogram: ",
			for i in range(0, 24):
			  vals = ["GET", "u8", (i+1) * 8]
			  total_sales = int(redis.execute_command("BITFIELD", "sales_histogram:time_of_day:" + event_name, *vals)[0])
			  print " {}/{}".format(i, total_sales),
			print "\n"
		time.sleep(1)

threads = []
threads.append(threading.Thread(target=listener_sales_analytics, args=("purchase_orders",)))
threads.append(threading.Thread(target=listener_events_analytics, args=("purchase_orders",)))
threads.append(threading.Thread(target=listener_customer_purchases, args=("purchase_orders",)))
threads.append(threading.Thread(target=print_statistics))

for i in range(len(threads)):
	threads[i].setDaemon(True)
	threads[i].start()

events = ["Womens Judo", "Mens 4x400"]
create_event(events[0])
create_event(events[1])

for i in range(50):
	purchase(events[random.randrange(0,2)])
	time.sleep(random.random())

