import io,json,sqlite3
from PIL import Image
import pytest
from return_intelligence.agents.reason import ReasonClassificationAgent
from return_intelligence.agents.retention import RetentionRecommendationAgent
from return_intelligence.agents.visual import VisualConditionAssessmentAgent
from return_intelligence.agents.early_warning import EarlyWarningAgent
from return_intelligence.db.connection import transaction
from return_intelligence.db.seed import seed_database,reset_database
from return_intelligence.domain.enums import EligibilityState,ReasonCategory
from return_intelligence.domain.errors import ValidationError
from return_intelligence.services.artifact_store import LocalPhotoStore

def test_reason_multilabel_and_sanitized_details():
    result=ReasonClassificationAgent().classify('Too small and the sole is broken')
    assert result.categories==(ReasonCategory.WRONG_SIZE,ReasonCategory.QUALITY);assert result.details['size_direction']=='too_small'
def test_reason_other_and_bounds():
    assert ReasonClassificationAgent().classify('Something unexpected').categories==(ReasonCategory.OTHER,)
    with pytest.raises(ValidationError):ReasonClassificationAgent().classify('  ')
def test_recommendations_are_larger_and_provably_in_stock(repo):
    item=repo.get_order_item('SYN-O-SIZE-001');item['similar_group']='RUNNER';classification=ReasonClassificationAgent().classify('too small')
    result=RetentionRecommendationAgent(repo).recommend(item,classification)
    assert result.options and all(float(x.size)>8 and x.available>0 for x in result.options);assert all(x.size!='10' for x in result.options)
def test_visual_fixture_rules_and_missing_angles():
    agent=VisualConditionAssessmentAgent();a=agent.assess('eligible_a_95');b=agent.assess('eligible_75');w=agent.assess('worn_ineligible');d=agent.assess('suspected_defect');missing=agent.assess('eligible_a_95',('front',))
    assert a.confidence==.95 and b.confidence==.75 and w.confidence==.97 and d.confidence==.96
    assert w.eligibility_state==EligibilityState.WORN_INELIGIBLE and w.preliminary_grade is None
    assert d.eligibility_state==EligibilityState.SUSPECTED_DEFECT and d.preliminary_grade is None
    assert not missing.evidence_sufficient and missing.preliminary_grade is None
def _image(width=800,height=600):
    out=io.BytesIO();Image.new('RGB',(width,height),'green').save(out,'PNG');return out.getvalue()
def test_local_photo_validation_uses_generated_names(tmp_path):
    store=LocalPhotoStore(tmp_path/'uploads');records=store.save('SYN-R', {a:_image() for a in store.required})
    assert len(records)==3 and all('client' not in x['local_path'] for x in records)
    with pytest.raises(ValidationError):store.save('SYN-R2',{'front':_image()})
    with pytest.raises(ValidationError):store.save('SYN-R3',{a:_image(100,100) for a in store.required})
def test_activity_log_is_append_only(repo):
    row=repo.create_return('SYN-R-APPEND','SYN-OI-001')
    with transaction(repo.db_path,True) as c:repo.activity(c,row['return_id'],'Test','CREATED','public rationale',{}, {})
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(repo.db_path,True) as c:c.execute("UPDATE activity_log SET rationale='changed'")
def test_seed_idempotent_and_reset_guard(repo,tmp_path):
    first=seed_database(repo.db_path,tmp_path);second=seed_database(repo.db_path,tmp_path);assert first==second
    with pytest.raises(ValueError):reset_database(tmp_path/'outside.db',tmp_path,True)
