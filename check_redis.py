import redis

r = redis.Redis(decode_responses=True)
keys = r.keys('clicks:*')

for key in sorted(keys):
    print(key, '->', dict(r.hgetall(key)))