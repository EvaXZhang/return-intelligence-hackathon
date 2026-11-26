"""Plain local function with a Lambda-compatible dictionary signature."""
from ...agents.reason import ReasonClassificationAgent

def handler(event,context=None):
    result=ReasonClassificationAgent().classify(event.get('reason',''))
    return {'statusCode':200,'body':result.model_dump(mode='json'),'runtime':'local pure Python'}
