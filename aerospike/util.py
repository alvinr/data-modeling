def removeKey((key, meta, bins)):
    client.remove(key)

def cleanOneSet(namespace, sname):
    scan = client.scan(namespace, sname)
    scan.foreach( removeKey )

def clean():
    cleanOneSet("test", "users")
    cleanOneSet("test", "events")
    cleanOneSet("test", "products")
    cleanOneSet("test", "lookups")

