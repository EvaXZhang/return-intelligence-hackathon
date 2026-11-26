def handler(event,context=None):
    required=('return_id','destination_id','mode')
    missing=[key for key in required if not event.get(key)]
    if missing:return {'statusCode':400,'body':{'error':'missing fields','fields':missing}}
    return {'statusCode':200,'body':{'return_id':event['return_id'],'destination_id':event['destination_id'],'mode':event['mode'],'marking':'DEMO / NOT VALID FOR SHIPPING','network_used':False},'runtime':'local pure Python'}
