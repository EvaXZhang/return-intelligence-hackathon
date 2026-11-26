import json
from pathlib import Path
import pytest
from return_intelligence.domain.errors import PolicyViolation
from return_intelligence.services.supervisor import SupervisorService
from tests.conftest import advance_to_photos

def test_size_exchange_persists_and_triggers_fifth_complaint_alert(service,repo):
    row=service.start_return('SYN-O-SIZE-001');rid=row['return_id'];result=service.submit_reason(rid,'The shoes are too small');option=result['recommendation']['options'][0]['option_id'];saved=service.record_decision(rid,'EXCHANGE',option,operation_id='size-decision')
    assert saved['photos_required'];alert=repo.one('SELECT * FROM early_warning_alerts');assert alert['complaint_count']==5 and alert['units_sold']==25 and alert['complaint_rate']==.2 and alert['lift']>=2 and 'not a confirmed defect' in alert['recommendation'].lower()
def test_early_warning_below_minimum_and_denominator_guard(service,repo):
    rid=advance_to_photos(service,'SYN-O-A95-001','wrong color')
    assert repo.one('SELECT count(*) n FROM early_warning_alerts')['n']==0
def test_eligible_a_95_auto_routes_retail_and_generates_marked_pdf(service,repo):
    rid=advance_to_photos(service,'SYN-O-A95-001','wrong color');result=service.submit_photos(rid,'eligible_a_95');assert result['state']=='READY_TO_ROUTE';assert repo.open_review(rid) is None
    # The gate confidence is staff-only: hidden in the customer view, kept in the staff view.
    before=service.get_customer_view(rid);assert before['final_grade']=='A' and before['simulated_calibrated_confidence'] is None and service.get_staff_view(rid)['request']['simulated_calibrated_confidence']==.95
    service.select_fulfillment_mode(rid,'SHIP');route=service.route_return(rid);assert route['decision']['destination_type']=='RETAIL_STORE';artifact=service.generate_artifact(rid);data=Path(artifact.local_path).read_bytes();assert b'DEMO / NOT VALID FOR SHIPPING' in data;assert service.get_customer_view(rid)['state']=='COMPLETED_RETURN'
def test_a_retail_dropoff_creates_demo_confirmation(service):
    rid=advance_to_photos(service,'SYN-O-A95-001','wrong color');service.submit_photos(rid,'eligible_a_95');service.select_fulfillment_mode(rid,'DROPOFF');route=service.route_return(rid);assert route['decision']['destination_id']=='SYN-STORE-1';artifact=service.generate_artifact(rid);assert artifact.artifact_type=='DEMO_DROPOFF_CONFIRMATION'
def test_low_confidence_blocks_until_human_override(service):
    rid=advance_to_photos(service,'SYN-O-LOW75-001');result=service.submit_photos(rid,'eligible_75');assert result['state']=='AWAITING_REVIEW';assert service.repo.open_review(rid)
    with pytest.raises(PolicyViolation):service.route_return(rid)
    row=service.resolve_review(rid,'OVERRIDE_C','Synthetic fixture review');assert row['final_grade']=='C' and row['condition_state']=='ELIGIBLE_UNWORN'
    service.select_fulfillment_mode(rid,'SHIP');route=service.route_return(rid);assert route['decision']['destination_type']=='COMPANY_WAREHOUSE'
def test_unclear_retakes_never_grade_or_route(service):
    rid=advance_to_photos(service,'SYN-O-UNCLEAR-001');result=service.submit_photos(rid,'unclear');row=service.get_customer_view(rid);assert result['state']=='RETAKE_REQUIRED' and row['final_grade'] is None and row['preliminary_grade'] is None
    with pytest.raises(PolicyViolation):service.route_return(rid)
def test_worn_is_rejected_not_grade_c_and_cannot_fulfill(service):
    rid=advance_to_photos(service,'SYN-O-WORN-001');service.submit_photos(rid,'worn_ineligible');row=service.get_customer_view(rid);assert row['state']=='INELIGIBLE_CLOSED' and row['final_grade'] is None
    with pytest.raises(PolicyViolation):service.generate_artifact(rid)
def test_suspected_defect_is_investigation_hold(service):
    rid=advance_to_photos(service,'SYN-O-DEFECT-001','sole is broken quality issue');service.submit_photos(rid,'suspected_defect');row=service.get_customer_view(rid);assert row['state']=='DEFECT_HOLD' and row['destination_type'] is None and row['final_grade'] is None
    with pytest.raises(PolicyViolation):service.generate_artifact(rid)
# v2 (D6): delivered delays run the normal flow and missing items reship, so the SERVICE path covers
# wrong-item and undelivered-delay cases; see tests/test_resolution_paths.py for the new paths.
@pytest.mark.parametrize(('order','reason'),[('SYN-O-COLOR-001','I received the wrong item'),('SYN-O-MISSING-001','shipping is delayed')])
def test_service_issues_require_no_photos_or_label(service,order,reason):
    row=service.start_return(order);rid=row['return_id'];service.submit_reason(rid,reason);result=service.record_decision(rid,'SERVICE_RESOLUTION');assert result['state']=='COMPLETED_SERVICE' and not result['photos_required']
    with pytest.raises(PolicyViolation):service.submit_photos(rid,'eligible_a_95')
def test_seasonal_sandal_stays_a_but_routes_outlet(service):
    rid=advance_to_photos(service,'SYN-O-SANDAL-001','wrong color');service.submit_photos(rid,'eligible_a_95');service.select_fulfillment_mode(rid,'SHIP');route=service.route_return(rid);row=service.get_customer_view(rid);assert row['final_grade']=='A' and route['seasonality']['flag']==1 and route['decision']['destination_type']=='OUTLET'
def test_seeded_grade_b_routes_outlet_after_review(service):
    rid=advance_to_photos(service,'SYN-O-B-001');service.submit_photos(rid,'eligible_75');service.resolve_review(rid,'APPROVE');service.select_fulfillment_mode(rid,'SHIP');assert service.route_return(rid)['decision']['destination_type']=='OUTLET'
def test_fulfillment_gates_direct_and_review(service):
    rid=advance_to_photos(service,'SYN-O-A95-001')
    with pytest.raises(PolicyViolation):service.generate_artifact(rid)
    service.submit_photos(rid,'eligible_75')
    with pytest.raises(PolicyViolation):service.generate_artifact(rid)
def test_restart_persistence_includes_history_route_artifact(service,repo,tmp_path):
    rid=advance_to_photos(service,'SYN-O-A95-001','wrong color');service.submit_photos(rid,'eligible_a_95');service.select_fulfillment_mode(rid,'SHIP');service.route_return(rid);service.generate_artifact(rid)
    restarted=SupervisorService(type(repo)(repo.db_path),tmp_path/'artifacts','WINTER');view=restarted.get_staff_view(rid);assert view['request']['state']=='COMPLETED_RETURN' and view['request']['route'] and view['request']['artifacts'] and view['decisions'] and view['activity']
def test_decision_operation_is_idempotent(service,repo):
    row=service.start_return('SYN-O-A95-001');rid=row['return_id'];service.submit_reason(rid,'wrong color');first=service.record_decision(rid,'REFUND',operation_id='same');second=service.record_decision(rid,'REFUND',operation_id='same');assert first==second and repo.one('SELECT count(*) n FROM decision_events WHERE return_id=?',(rid,))['n']==1


def test_exchange_reserves_inventory_then_releases_replacement_after_original_return(service, repo):
    request = service.start_return('SYN-O-SIZE-001')
    return_id = request['return_id']
    result = service.submit_reason(return_id, 'The shoes are too small')
    option = result['recommendation']['options'][0]
    inventory_key = (option['sku'], option['size'], option['color'], option['destination_id'])
    before = repo.one(
        'SELECT on_hand,reserved FROM inventory WHERE sku=? AND size=? AND color=? AND destination_id=?',
        inventory_key,
    )
    decision = service.record_decision(return_id, 'EXCHANGE', option['option_id'], operation_id='complete-exchange')
    reserved = repo.one(
        'SELECT on_hand,reserved FROM inventory WHERE sku=? AND size=? AND color=? AND destination_id=?',
        inventory_key,
    )
    assert decision['exchange']['exchange_status'] == 'RESERVED_PENDING_ORIGINAL_RETURN'
    assert reserved['reserved'] == before['reserved'] + 1
    assert service.get_customer_view(return_id)['exchange']['size'] == '9'

    service.submit_photos(return_id, 'eligible_a_95')
    service.select_fulfillment_mode(return_id, 'SHIP')
    service.route_return(return_id)
    artifact = service.generate_artifact(return_id)
    waiting = service.get_customer_view(return_id)
    assert artifact.artifact_type == 'DEMO_EXCHANGE_RETURN_LABEL'
    assert waiting['state'] == 'AWAITING_ORIGINAL_RETURN'

    completed = service.complete_exchange(return_id)
    released = repo.one(
        'SELECT on_hand,reserved FROM inventory WHERE sku=? AND size=? AND color=? AND destination_id=?',
        inventory_key,
    )
    assert completed['state'] == 'COMPLETED_EXCHANGE'
    assert completed['exchange']['exchange_status'] == 'REPLACEMENT_RELEASED_DEMO'
    assert released['reserved'] == before['reserved']
    assert released['on_hand'] == before['on_hand'] - 1


def test_refund_shipping_costs_nine_dollars(service):
    return_id = advance_to_photos(service, 'SYN-O-A95-001', 'wrong color', 'REFUND')
    service.submit_photos(return_id, 'eligible_a_95')
    assert service.available_fulfillment_modes(return_id) == ('SHIP', 'DROPOFF')
    service.select_fulfillment_mode(return_id, 'SHIP')
    route = service.route_return(return_id)
    view = service.get_customer_view(return_id)
    assert route['decision']['return_fee'] == 9.0
    assert route['decision']['intake_location_id'] == 'SYN-STORE-1'
    assert view['return_store_name'] == 'ALDO Downtown Demo Store'
    assert '(DEMO)' in view['return_store_address']
    assert view['return_fee'] == 9.0


@pytest.mark.parametrize(
    ('order_id', 'resolution', 'expected_destination_type'),
    [
        ('SYN-O-B-001', 'APPROVE', 'OUTLET'),
        ('SYN-O-C-001', 'OVERRIDE_C', 'COMPANY_WAREHOUSE'),
    ],
)
def test_refund_store_dropoff_is_free_while_final_matrix_route_is_preserved(
    service, order_id, resolution, expected_destination_type
):
    return_id = advance_to_photos(service, order_id, 'I prefer another style', 'REFUND')
    service.submit_photos(return_id, 'eligible_75')
    service.resolve_review(return_id, resolution)
    assert service.available_fulfillment_modes(return_id) == ('SHIP', 'DROPOFF')
    service.select_fulfillment_mode(return_id, 'DROPOFF')
    route = service.route_return(return_id)
    view = service.get_customer_view(return_id)
    assert route['decision']['destination_type'] == expected_destination_type
    assert route['decision']['return_fee'] == 0.0
    assert route['decision']['intake_location_id'] == 'SYN-STORE-1'
    assert view['dropoff_location_id'] == 'SYN-STORE-1'
    assert view['return_fee'] == 0.0


def test_customer_view_and_pdf_hide_internal_outlet_routing_but_staff_can_see_it(service):
    return_id = advance_to_photos(service, 'SYN-O-B-001', 'I prefer another style', 'REFUND')
    service.submit_photos(return_id, 'eligible_75')
    service.resolve_review(return_id, 'APPROVE')
    service.select_fulfillment_mode(return_id, 'DROPOFF')
    route = service.route_return(return_id)
    assert route['decision']['destination_type'] == 'OUTLET'

    customer = service.get_customer_view(return_id)
    staff = service.get_staff_view(return_id)['request']
    assert customer['destination_type'] is None
    assert customer['selected_destination_id'] is None
    assert customer['routing_reason'] is None
    assert customer['route'] is None
    assert customer['return_store_name'] == 'ALDO Downtown Demo Store'
    assert '(DEMO)' in customer['return_store_address']
    assert staff['destination_type'] == 'OUTLET'
    assert staff['selected_destination_id'] == route['decision']['destination_id']
    assert staff['route']['destination_type'] == 'OUTLET'

    artifact = service.generate_artifact(return_id)
    pdf_text = Path(artifact.local_path).read_bytes()
    assert b'ALDO Downtown Demo Store' in pdf_text
    assert b'SYN-OUTLET-1' not in pdf_text
    assert b'COMPANY_WAREHOUSE' not in pdf_text
