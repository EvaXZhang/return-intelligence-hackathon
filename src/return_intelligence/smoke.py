from __future__ import annotations
import tempfile
from pathlib import Path
from .db.repositories import Repository
from .db.seed import seed_database
from .services.supervisor import SupervisorService

def run_smoke(root:Path|None=None):
    with tempfile.TemporaryDirectory() as tmp:
        base=Path(tmp);db=base/'data'/'smoke.db';seed_database(db,base);service=SupervisorService(Repository(db),base/'artifacts','WINTER')
        row=service.start_return('SYN-O-A95-001');rid=row['return_id'];service.submit_reason(rid,'Wrong color');service.record_decision(rid,'REFUND',operation_id='smoke-decision');service.submit_photos(rid,'eligible_a_95');service.select_fulfillment_mode(rid,'SHIP');route=service.route_return(rid);artifact=service.generate_artifact(rid)
        return {'state':service.get_customer_view(rid)['state'],'destination_type':route['decision']['destination_type'],'artifact':artifact.demo_marking,'aws_calls':0}
def main():print(run_smoke())
if __name__=='__main__':main()
