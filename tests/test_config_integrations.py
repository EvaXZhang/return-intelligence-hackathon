import sys
from pathlib import Path
import pytest
from return_intelligence.config import AppConfig,ConfigurationError,IntegrationDisabledError
from return_intelligence.providers import create_provider
from return_intelligence.integrations.lambda_handlers.reason_policy import handler as reason_handler
from return_intelligence.integrations.lambda_handlers.routing import handler as routing_handler
from return_intelligence.integrations.lambda_handlers.early_warning import handler as warning_handler

def test_safe_default_is_simulated_and_does_not_import_boto3(tmp_path,monkeypatch):
    monkeypatch.setenv('AI_BACKEND','simulated');monkeypatch.setenv('AWS_INTEGRATION_ENABLED','false');monkeypatch.setenv('DEPLOYMENT_ENABLED','false');sys.modules.pop('boto3',None)
    provider=create_provider(AppConfig.from_env(tmp_path));assert provider.provider_kind=='simulated';assert 'boto3' not in sys.modules
def test_bedrock_incomplete_opt_in_fails_before_sdk_import(tmp_path,monkeypatch):
    monkeypatch.setenv('AI_BACKEND','bedrock');monkeypatch.setenv('AWS_INTEGRATION_ENABLED','false');monkeypatch.setenv('BEDROCK_MODEL_ID','');sys.modules.pop('boto3',None)
    with pytest.raises(IntegrationDisabledError):AppConfig.from_env(tmp_path)
    assert 'boto3' not in sys.modules
def test_unknown_backend_and_deployment_fail_closed(tmp_path,monkeypatch):
    monkeypatch.setenv('AI_BACKEND','unknown')
    with pytest.raises(ConfigurationError):AppConfig.from_env(tmp_path)
    monkeypatch.setenv('AI_BACKEND','simulated');monkeypatch.setenv('DEPLOYMENT_ENABLED','true')
    with pytest.raises(IntegrationDisabledError):AppConfig.from_env(tmp_path)
def test_local_lambda_compatible_handlers():
    assert reason_handler({'reason':'shoes are too small'})['body']['categories']==['Wrong Size']
    assert routing_handler({'condition':'A','seasonality_flag':1})['body']['destination_type']=='OUTLET'
    assert warning_handler({'complaint_count':5,'units_sold':25,'baseline_rate':.01})['body']['alerted'] is True
