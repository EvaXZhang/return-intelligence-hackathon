from ...domain.early_warning_rules import evaluate_rates


def handler(event,context=None):
    count=int(event.get('complaint_count',0));sold=int(event.get('units_sold',0));baseline=float(event.get('baseline_rate',0))
    # baseline_rate <= 0 means no comparable baseline: the shared rule then alerts on minimum count + rate.
    result=evaluate_rates(count,sold,baseline)
    alerted=result['alerted']
    return {'statusCode':200,'body':{'alerted':alerted,'complaint_rate':result['rate'],'lift':result['lift'] or 0,'baseline_available':result['baseline_available'],'wording':'Suspected pattern—investigation recommended' if alerted else 'No threshold-crossing suspected pattern'},'runtime':'local pure Python'}
