from ...domain.routing_matrix import route_type

def handler(event,context=None):
    return {'statusCode':200,'body':{'destination_type':route_type(event['condition'],int(event['seasonality_flag'])).value},'runtime':'local pure Python'}
