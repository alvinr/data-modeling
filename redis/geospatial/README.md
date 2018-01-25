# Geo-spatial
We are accustomed to location aware application like Uber, Yelp and others. The ability to create mapped locations into data structures that allow for quick access and manipulation is critical to create engaging experiences.

Redis provides Geospatial capabilities through a number of commands
* [GEOADD](https://redis.io/commands/geoadd)
* [GEOPOS](https://redis.io/commands/geopos)
* [GEODIST](https://redis.io/commands/geodist)
* [GEORADIUS](https://redis.io/commands/georadius)

 These can be combined to create powerful data structures to manipulate locations based objects.

 ## What is near me?
 Going back to our Olympic 2020 application, its clear that we may want to be able to find a venue or event that is near my current location. Lets see how we can do that.

```python
# Find venues with 5km of Tokyo Station
print redis.georadius("venue_locations", 139.771977, 35.668024, 5, "km", withdist=True)
``` 
The [GEORADIUS](https://redis.io/commands/georadius) provides a simple way to perform a distance based search for other geographical points records within a specific radius, in this example with 5km of Latitude ```35.668024``` and longitude ```139.771977```. Let put this query together with some data other geographical points and see what we can query:

```python
from redis import StrictRedis, WatchError
import os
import time
import random
import string
import json
from datetime import date

redis = StrictRedis(host=os.environ.get("REDIS_HOST", "localhost"), 
                    port=os.environ.get("REDIS_PORT", 6379),
                    db=0)
redis.flushall()

olympic_stadium = { 
	'venue': "Olympic Stadium",
  'capacity': 60000,
  'events': ["Athletics", "Football"],
  'geo': {'long': 139.76632, 'lat': 35.666754},
  'transit': ["Toei Odeo Line", "Chuo Main Line"]
}

nippon_budokan = {
	'venue': "Nippon Budokan",
	'capacity': 12000,
  'events': ["Judo", "Karate"],
  'geo': {'long': 139.75, 'lat': 35.693333},
  'transit':[ "Toei Shinjuku Line", "Tozai Line", "Hanzomon Line"]
}

makuhari_messe = {
	'venue': "Makuhari Messe",
	'capacity': 6000,
	'events': ["Fencing", "Taekwondo", "Wrestling"],
	'geo': {'long': 140.034722, 'lat': 35.648333},
	'transit': ["Keiyo Line"]
}

saitama_super_arena = { 
	'venue': "Saitama Super Arena",
  'capacity': 22000,
  'events': ["Basketball"],
  'geo': {'long': 139.630833, 'lat': 35.894889},
  'transit': ["Saitama-Shintoshin", "Takasaki Line", "Utsunomiya Line", "Keihin-Tōhoku Line", "Saikyō Line"]
}

international_stadium = { 
	'venue': "International Stadium Yokohama",
  'capacity': 70000,
  'events': ["Football"],
  'geo': {'long': 139.606247, 'lat': 35.510044},
  'transit': ["Tokaido Shinkansen", "Yokohama Line", "Blue Line"]
}

international_swimming_center = { 
	'venue': "Tokyo Tatsumi International Swimming Center",
  'capacity': 5000,
  'events': ["Water polo"],
  'geo': {'long': 139.818943, 'lat': 35.647668},
  'transit': ["Keiyo Line", "Rinkai Line", "Yurakucho Line"]
}

def create_venue(venue):
	p = redis.pipeline()
	p.hmset("venues:" + venue['venue'], venue)
	p.geoadd("venue_locations", venue['geo']['long'], venue['geo']['lat'], venue['venue'])
	p.execute()

create_venue(olympic_stadium)
create_venue(nippon_budokan)
create_venue(makuhari_messe)
create_venue(saitama_super_arena)
create_venue(international_stadium)
create_venue(international_swimming_center)
```

When we run the code we get the following:

```
>>> print redis.georadius("venue_locations", 139.771977, 35.668024, 5, "km", withdist=True)
[['Olympic Stadium', 0.5303], ['Tokyo Tatsumi International Swimming Center', 4.8107], ['Nippon Budokan', 3.4448]]
```

## What is going on internally?
In the example above, we can see that there are three points within 5km the geographical location provided (in this case Toyko Station). Redis actually stores the values as a Sorted Set:

```
127.0.0.1:6379> zrange venue_locations 0 -1
1) "International Stadium Yokohama"
2) "Olympic Stadium"
3) "Tokyo Tatsumi International Swimming Center"
4) "Nippon Budokan"
5) "Makuhari Messe"
6) "Saitama Super Arena"
```

The [ZRANGE](https://redis.io/commands/zrange) operation is used to examine the values in the key, since a Sorted Set is used to back the Geo-spatial data. You can see the names of the locations, but what about the Latitude and Longitude? Well, internally Redis stores these as a [GeoHash](https://en.wikipedia.org/wiki/Geohash) in 52 bits. You can see the Geohash by doing the following:

```
127.0.0.1:6379> geohash venue_locations "Olympic Stadium"
 1) "xn76ukytzk0"
```

This is more use for hacking and playing around with the internals of Redis, but you can always get the Latitude and Longitude directly:

```
127.0.0.1:6379> geopos venue_locations "Olympic Stadium"
 1) 1) "139.76632028818130493"
   2) "35.66675467929545817"
```

## Using the name of the location
In our ```venue_locations``` we are storing the geographic location, but also the name of the point - for example "Olympic Stadium". This allows us to find by the given name and then compute distances from that point. For example, lets say we want to find venues within 25km of "Olympic Stadium" - well that's simple:

```
>>> print redis.georadiusbymember("venue_locations", "Olympic Stadium", 25, "km", withdist=True)
[['Olympic Stadium', 0.0], ['Tokyo Tatsumi International Swimming Center', 5.2082], ['Nippon Budokan', 3.3035], ['International Stadium Yokohama', 22.6596], ['Makuhari Messe', 24.3428]]
```

We use the [GEORADIUSBYMEMBER](https://redis.io/commands/georadiusbymember) operator so find other geographic points that are within 25km of the point specified by the latitude and longitude of "Olympic Stadium". This provides a simple way to search based on point name for other points around it.

## What if we want to search on other criteria?
Its simple enough to create other geo-spatial keys based on other aspects of the data. For example, lets say we want to find venues 5km away from "Tokyo Station" on the "Keiyo" subway line. We now need to take our data and create a values for a geo key for each subway line:

```python
def create_event_transit_locations(venue):
	p = redis.pipeline()
	for i in range(len(venue['transit'])):
		p.geoadd("event_transit:" + venue['transit'][i], venue['geo']['long'], venue['geo']['lat'], venue['venue'])
	p.execute()

create_event_transit_locations(olympic_stadium)
create_event_transit_locations(nippon_budokan)
create_event_transit_locations(makuhari_messe)
create_event_transit_locations(saitama_super_arena)
create_event_transit_locations(international_stadium)
create_event_transit_locations(international_swimming_center)
```

If we run the code we see:

```
>>> print redis.georadius("event_transit:" + "Keiyo Line", 139.771977, 35.668024, 5, "km", withdist=True)
[['Tokyo Tatsumi International Swimming Center', 4.8107]]
```

By concatenating the subway line into the key name, we create a separate key for each line, and we just then need to add each matching geographic point into the list if its serviced by the "Keiyo" subway line.

# Distance between points
Its nice to know what's near me, but its often nice to know that distance as well. We can you this my using the name of the points we want to find the distance between:

```
>>> # Find the distance between locations on the "Keiyo Line"
>>> print redis.geodist("event_transit:" + "Keiyo Line", "Makuhari Messe", "Tokyo Tatsumi International Swimming Center", "km")
 19.503
```

## Summary
Redis makes its simple to create geo-spatially aware structures that you can compute radius, distance and other measures.
