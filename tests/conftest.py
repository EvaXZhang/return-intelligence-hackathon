from pathlib import Path
import pytest
from return_intelligence.db.repositories import Repository
from return_intelligence.db.seed import seed_database
from return_intelligence.services.supervisor import SupervisorService

@pytest.fixture
def repo(tmp_path):
    db=tmp_path/'data'/'test.db';seed_database(db,tmp_path);return Repository(db)
@pytest.fixture
def service(repo,tmp_path):return SupervisorService(repo,tmp_path/'artifacts','WINTER')
def advance_to_photos(service,order,reason='I dislike these shoes',decision='REFUND'):
    row=service.start_return(order);rid=row['return_id'];service.submit_reason(rid,reason);service.record_decision(rid,decision);return rid
