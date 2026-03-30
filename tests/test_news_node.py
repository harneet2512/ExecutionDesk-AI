import pytest
import json
from unittest.mock import Mock, AsyncMock, patch
from backend.orchestrator.nodes.news_node import execute

@pytest.fixture
def mock_conn():
    with patch("backend.orchestrator.nodes.news_node.get_conn") as m:
        mock_db = Mock()
        m.return_value.__enter__.return_value = mock_db
        yield mock_db

@pytest.fixture
def mock_news_service():
    with patch("backend.orchestrator.nodes.news_node.news_service") as m:
        yield m

@pytest.mark.asyncio
async def test_news_node_paper_mode(mock_conn, mock_news_service):
    # Setup
    cursor = mock_conn.cursor.return_value
    
    # 1. Mock run details (PAPER)
    cursor.fetchone.side_effect = [
        {"news_enabled": 1},  # news_enabled check
        {"execution_mode": "PAPER", "source_run_id": None, "created_at": "2024-01-01T10:00:00Z"}, # run details
        {"outputs_json": json.dumps({"top_symbol": "BTC"})} # signals
    ]
    
    # 2. Mock create_brief
    mock_news_service.create_brief.return_value = {"assets": [], "blockers": []}
    
    # Run
    result = await execute("run_1", "node_1", "tenant_1")
    
    # Verify
    mock_news_service.create_brief.assert_called_once()
    args, kwargs = mock_news_service.create_brief.call_args
    assert "BTC" in args[1] # candidates
    
    # Verify artifact storage
    assert cursor.execute.call_count >= 2 # select run, select signals, insert artifact
    insert_call = [args for args in cursor.execute.call_args_list if "INSERT INTO run_artifacts" in args[0][0]]
    assert insert_call

@pytest.mark.asyncio
async def test_news_node_replay_mode(mock_conn, mock_news_service):
    # Setup
    cursor = mock_conn.cursor.return_value
    
    # 1. Mock run details (REPLAY)
    cursor.fetchone.side_effect = [
        {"news_enabled": 1},  # news_enabled check
        {"execution_mode": "REPLAY", "source_run_id": "source_1", "created_at": "2024-01-01T10:00:00Z"},
        {"outputs_json": json.dumps({"top_symbol": "BTC"})}
    ]
    
    # 2. Mock create_brief_from_source
    mock_news_service.create_brief_from_source.return_value = {"assets": [], "source_run_id": "source_1"}
    
    # Run
    result = await execute("run_2", "node_1", "tenant_1")
    
    # Verify
    mock_news_service.create_brief_from_source.assert_called_once_with("run_2", "source_1")
    mock_news_service.create_brief.assert_not_called()
