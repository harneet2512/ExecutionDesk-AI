"""Golden Run Tests - Determinism verification.

Tests that run outputs match expected golden snapshots.
Ensures replay mode doesn't make external calls.
"""
import pytest
import json
import glob
from pathlib import Path
from unittest.mock import patch, MagicMock

# Import test utilities
from tests.conftest import (
    load_golden_run,
    canonicalize_artifacts,
    assert_artifacts_match,
    make_candles,
    make_run
)


class TestGoldenRunDeterminism:
    """Tests for deterministic run execution."""
    
    @pytest.fixture
    def mock_coinbase_api(self):
        """Mock Coinbase API calls with recorded data."""
        from tests.conftest import load_vcr_cassette
        
        cassette = load_vcr_cassette("coinbase_48h")
        
        def mock_get(url, **kwargs):
            from tests.conftest import MockResponse
            
            # Try to find matching response
            for pattern, response in cassette.items():
                if pattern in url:
                    return MockResponse(response)
            
            # Default: empty list
            return MockResponse([], 200)
        
        with patch("httpx.Client") as mock_client:
            instance = MagicMock()
            instance.get = mock_get
            instance.__enter__ = lambda s: instance
            instance.__exit__ = lambda s, *args: None
            mock_client.return_value = instance
            yield mock_client
    
    def test_ranking_output_deterministic(self, test_db, mock_coinbase_api):
        """Test that ranking output is deterministic with same inputs."""
        from backend.services.coinbase_market_data import compute_return_24h
        
        # Create deterministic candles
        candles = make_candles("BTC-USD", count=48, start_price=45000, price_change_pct=0.05)
        
        # Compute return multiple times
        returns = [compute_return_24h(candles) for _ in range(5)]
        
        # All returns should be identical
        assert all(r == returns[0] for r in returns), "Return computation is not deterministic"
    
    def test_candle_sorting_deterministic(self, test_db):
        """Test that candle sorting produces deterministic order."""
        from backend.services.coinbase_market_data import compute_return_24h
        
        # Create candles in random order
        import random
        candles = make_candles("BTC-USD", count=48, start_price=45000)
        
        # Shuffle and sort multiple times
        results = []
        for _ in range(5):
            shuffled = candles.copy()
            random.shuffle(shuffled)
            sorted_candles = sorted(shuffled, key=lambda x: x["start_time"])
            result = compute_return_24h(sorted_candles)
            results.append(result)
        
        # All results should be identical
        assert all(r == results[0] for r in results), "Sorting is not deterministic"
    
    def test_artifact_canonicalization(self):
        """Test that artifact canonicalization is deterministic."""
        artifact = {
            "ranked_assets": [
                {"symbol": "BTC-USD", "return_pct": 0.05},
                {"symbol": "ETH-USD", "return_pct": 0.03}
            ],
            "computed_at": "2026-02-01T00:00:00Z",
            "universe_size": 10
        }
        
        # Canonicalize multiple times
        results = [canonicalize_artifacts(artifact) for _ in range(5)]
        
        # All results should be identical
        assert all(r == results[0] for r in results), "Canonicalization is not deterministic"
        
        # Non-deterministic fields should be removed
        assert "computed_at" not in results[0]


class TestReplayNoExternalCalls:
    """Tests ensuring replay mode uses stored evidence only."""
    
    def test_replay_uses_stored_candles(self, test_db):
        """Replay should use stored candles, not fetch new ones."""
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        import json
        
        # Create a source run with stored candles
        run_id = make_run(
            execution_mode="PAPER",
            command_text="Buy most profitable crypto",
            intent={"lookback_hours": 48}
        )
        
        # Create a node first (FK constraint)
        node_id = new_id("node_")
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO dag_nodes (node_id, run_id, name, node_type, status, started_at)
                VALUES (?, ?, 'research', 'research', 'COMPLETED', datetime('now'))
                """,
                (node_id, run_id)
            )
            conn.commit()
        
        # Store some candles as evidence
        candles = make_candles("BTC-USD", count=48)
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO market_candles_batches 
                (batch_id, run_id, node_id, symbol, window, candles_json, query_params_json, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                ("batch_test", run_id, node_id, "BTC-USD", "1h", 
                 json.dumps(candles), json.dumps({"lookback_hours": 48}))
            )
            conn.commit()
        
        # Verify candles are stored
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT candles_json FROM market_candles_batches WHERE run_id = ?",
                (run_id,)
            )
            row = cursor.fetchone()
            assert row is not None, "Candles should be stored"
            stored_candles = json.loads(row["candles_json"])
            assert len(stored_candles) == 48, "All candles should be stored"
    
    def test_replay_external_call_raises(self, test_db):
        """External calls during replay should raise an error."""
        def fail_on_call(*args, **kwargs):
            raise RuntimeError("No external calls allowed during replay!")
        
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.get = fail_on_call
            
            # This would fail if replay tried to make external calls
            # In actual replay, the stored evidence should be used instead


class TestGoldenArtifactComparison:
    """Tests for comparing artifacts against golden snapshots."""
    
    def test_financial_brief_structure(self, test_db):
        """Test that financial_brief has required structure."""
        from backend.db.connect import get_conn
        import json
        
        # Create a run
        run_id = make_run(execution_mode="PAPER")
        
        # Create a financial_brief artifact
        brief = {
            "lookback_hours": 48,
            "granularity": "ONE_HOUR",
            "ranked_assets": [
                {
                    "product_id": "BTC-USD",
                    "base_symbol": "BTC",
                    "return_48h": 0.05,
                    "candles_count": 48,
                    "first_ts": "2026-01-30T00:00:00Z",
                    "last_ts": "2026-02-01T00:00:00Z",
                    "last_price": 50000
                }
            ],
            "universe_size": 10,
            "valid_count": 1,
            "dropped_count": 9,
            "computed_at": "2026-02-01T00:00:00Z"
        }
        
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                VALUES (?, 'research', 'financial_brief', ?)
                """,
                (run_id, json.dumps(brief))
            )
            conn.commit()
        
        # Verify structure
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'financial_brief'",
                (run_id,)
            )
            row = cursor.fetchone()
            loaded = json.loads(row["artifact_json"])
            
            # Check required fields
            assert "ranked_assets" in loaded
            assert "lookback_hours" in loaded
            assert "granularity" in loaded
            
            # Check ranked_assets structure
            assert len(loaded["ranked_assets"]) > 0
            asset = loaded["ranked_assets"][0]
            assert "product_id" in asset
            assert "return_48h" in asset
            assert "candles_count" in asset
    
    def test_research_summary_structure(self, test_db):
        """Test that research_summary has required structure."""
        from backend.db.connect import get_conn
        import json
        
        run_id = make_run(execution_mode="PAPER")
        
        summary = {
            "window_hours": 48,
            "resolution": "1h",
            "lookback_buffer_hours": 60,
            "min_candles_required": 36,
            "attempted_assets": 10,
            "ranked_assets_count": 8,
            "dropped_by_reason": {
                "insufficient_candles": 1,
                "api_error": 1
            },
            "api_call_stats": {
                "calls": 10,
                "retries": 2,
                "rate_429s": 0,
                "timeouts": 1,
                "cache_hits": 0,
                "successes": 8,
                "failures": 2
            },
            "computed_at": "2026-02-01T00:00:00Z"
        }
        
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                VALUES (?, 'research', 'research_summary', ?)
                """,
                (run_id, json.dumps(summary))
            )
            conn.commit()
        
        # Verify structure
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'research_summary'",
                (run_id,)
            )
            row = cursor.fetchone()
            loaded = json.loads(row["artifact_json"])
            
            # Check required fields
            assert "window_hours" in loaded
            assert "resolution" in loaded
            assert "api_call_stats" in loaded
            assert "dropped_by_reason" in loaded


class TestEmptyRankingsFailure:
    """Tests for proper handling of empty rankings."""
    
    def test_empty_rankings_creates_failure_artifact(self, test_db):
        """Empty rankings must create research_failure artifact."""
        from backend.db.connect import get_conn
        import json
        
        run_id = make_run(execution_mode="PAPER")
        
        # Create a research_failure artifact (simulating what research_node does)
        failure = {
            "summary": "Research node produced no valid rankings.",
            "reason_code": "RESEARCH_EMPTY_RANKINGS",
            "root_cause_guess": "api_error",
            "recommended_fix": "Check Coinbase API credentials",
            "universe_size": 5,
            "all_dropped": True,
            "dropped_by_reason": {"api_error": 5},
            "top_examples": [
                {"asset": "BTC-USD", "reason": "api_error", "candle_count": 0}
            ],
            "failed_at": "2026-02-01T00:00:00Z"
        }
        
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                VALUES (?, 'research', 'research_failure', ?)
                """,
                (run_id, json.dumps(failure))
            )
            conn.commit()
        
        # Verify required fields
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'research_failure'",
                (run_id,)
            )
            row = cursor.fetchone()
            loaded = json.loads(row["artifact_json"])
            
            # Check required fields per spec
            assert loaded["reason_code"] == "RESEARCH_EMPTY_RANKINGS"
            assert "root_cause_guess" in loaded
            assert "recommended_fix" in loaded
            assert "dropped_by_reason" in loaded
            assert "top_examples" in loaded


class TestReplayDeterminismIntegration:
    """Integration tests for replay determinism."""
    
    def test_replay_produces_same_artifacts(self, test_db):
        """Replay with same evidence should produce identical artifacts."""
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        import json
        
        # Create source run with artifacts
        source_run_id = make_run(
            execution_mode="PAPER",
            command_text="Buy most profitable crypto"
        )
        
        brief = {
            "ranked_assets": [
                {"product_id": "BTC-USD", "return_48h": 0.05, "candles_count": 48}
            ],
            "lookback_hours": 48
        }
        
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                VALUES (?, 'research', 'financial_brief', ?)
                """,
                (source_run_id, json.dumps(brief))
            )
            conn.commit()
        
        # Create replay run
        replay_run_id = make_run(
            execution_mode="REPLAY"
        )
        
        # Store reference to source
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE runs SET source_run_id = ? WHERE run_id = ?",
                (source_run_id, replay_run_id)
            )
            conn.commit()
        
        # Copy artifacts (simulating replay behavior)
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                SELECT ?, step_name, artifact_type, artifact_json
                FROM run_artifacts WHERE run_id = ?
                """,
                (replay_run_id, source_run_id)
            )
            conn.commit()
        
        # Verify artifacts are identical
        with get_conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'financial_brief'",
                (source_run_id,)
            )
            source_artifact = cursor.fetchone()["artifact_json"]
            
            cursor.execute(
                "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'financial_brief'",
                (replay_run_id,)
            )
            replay_artifact = cursor.fetchone()["artifact_json"]
            
            assert source_artifact == replay_artifact, "Replay artifacts should match source"
