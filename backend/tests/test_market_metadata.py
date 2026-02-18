"""Unit tests for MarketMetadataService."""
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from backend.services.market_metadata import (
    MarketMetadataService,
    MetadataResult,
    MetadataErrorCode
)


@pytest.fixture
def service():
    """Create a MarketMetadataService instance."""
    return MarketMetadataService()


@pytest.fixture
def mock_product_data():
    """Mock product data from Coinbase API."""
    return {
        "product_id": "BTC-USD",
        "base_currency_id": "BTC",
        "quote_currency_id": "USD",
        "base_min_size": "0.00001",
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "min_market_funds": "1.00",
        "status": "online"
    }


@pytest.mark.asyncio
async def test_get_product_details_cache_hit(service, mock_product_data):
    """Test that cache hit returns cached data without API call."""
    with patch.object(service, '_get_from_cache', return_value=mock_product_data):
        with patch.object(service, '_fetch_from_api_with_retry') as mock_fetch:
            result = await service.get_product_details("BTC-USD")
            
            assert result.success is True
            assert result.data == mock_product_data
            assert result.used_stale_cache is False
            assert result.error_code == MetadataErrorCode.SUCCESS
            mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_get_product_details_api_success(service, mock_product_data):
    """Test successful API fetch when cache misses."""
    with patch.object(service, '_get_from_cache', return_value=None):
        with patch.object(service, '_fetch_from_api_with_retry', return_value=MetadataResult(
            success=True,
            data=mock_product_data,
            error_code=MetadataErrorCode.SUCCESS,
            error_message=None,
            used_stale_cache=False,
            cache_age_seconds=0
        )):
            with patch.object(service, '_save_to_cache') as mock_save:
                result = await service.get_product_details("BTC-USD")
                
                assert result.success is True
                assert result.data == mock_product_data
                assert result.used_stale_cache is False
                mock_save.assert_called_once_with("BTC-USD", mock_product_data)


@pytest.mark.asyncio
async def test_get_product_details_fallback_to_stale_cache(service, mock_product_data):
    """Test fallback to stale cache when API fails."""
    with patch.object(service, '_get_from_cache') as mock_cache:
        # First call (fresh cache) returns None, second call (stale cache) returns data
        mock_cache.side_effect = [None, mock_product_data]
        
        with patch.object(service, '_fetch_from_api_with_retry', return_value=MetadataResult(
            success=False,
            data=None,
            error_code=MetadataErrorCode.API_TIMEOUT,
            error_message="Timeout after 3 attempts",
            used_stale_cache=False,
            cache_age_seconds=None
        )):
            result = await service.get_product_details("BTC-USD", allow_stale=True)
            
            assert result.success is True
            assert result.data == mock_product_data
            assert result.used_stale_cache is True
            assert "API failed" in result.error_message


@pytest.mark.asyncio
async def test_get_product_details_no_cache_available(service):
    """Test failure when API fails and no cache available."""
    with patch.object(service, '_get_from_cache', return_value=None):
        with patch.object(service, '_fetch_from_api_with_retry', return_value=MetadataResult(
            success=False,
            data=None,
            error_code=MetadataErrorCode.API_TIMEOUT,
            error_message="Timeout after 3 attempts",
            used_stale_cache=False,
            cache_age_seconds=None
        )):
            result = await service.get_product_details("BTC-USD")
            
            assert result.success is False
            assert result.data is None
            assert result.error_code == MetadataErrorCode.API_TIMEOUT
            assert "Timeout" in result.error_message


@pytest.mark.asyncio
async def test_fetch_from_api_with_retry_success_first_attempt(service, mock_product_data):
    """Test successful API fetch on first attempt."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"product": mock_product_data}
    
    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        
        result = await service._fetch_from_api_with_retry("BTC-USD")
        
        assert result.success is True
        assert result.data == mock_product_data
        assert result.error_code == MetadataErrorCode.SUCCESS


@pytest.mark.asyncio
async def test_fetch_from_api_with_retry_429_then_success(service, mock_product_data):
    """Test retry logic with 429 rate limit then success."""
    mock_response_429 = Mock()
    mock_response_429.status_code = 429
    
    mock_response_200 = Mock()
    mock_response_200.status_code = 200
    mock_response_200.json.return_value = {"product": mock_product_data}
    
    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=[mock_response_429, mock_response_200]
        )
        
        result = await service._fetch_from_api_with_retry("BTC-USD", max_retries=3)
        
        assert result.success is True
        assert result.data == mock_product_data


@pytest.mark.asyncio
async def test_fetch_from_api_with_retry_timeout_exhausted(service):
    """Test all retries exhausted on timeout."""
    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )
        
        result = await service._fetch_from_api_with_retry("BTC-USD", max_retries=3)
        
        assert result.success is False
        assert result.error_code == MetadataErrorCode.API_TIMEOUT
        assert "Failed after 3 attempts" in result.error_message


@pytest.mark.asyncio
async def test_fetch_from_api_with_retry_404_no_retry(service):
    """Test that 404 errors don't retry."""
    mock_response = Mock()
    mock_response.status_code = 404
    
    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        
        result = await service._fetch_from_api_with_retry("INVALID-USD", max_retries=3)
        
        assert result.success is False
        assert result.error_code == MetadataErrorCode.PRODUCT_NOT_FOUND
        # Should only call once, no retries for 404
        assert mock_client.return_value.__aenter__.return_value.get.call_count == 1


@pytest.mark.asyncio
async def test_fetch_from_api_with_retry_500_then_success(service, mock_product_data):
    """Test retry logic with 500 server error then success."""
    mock_response_500 = Mock()
    mock_response_500.status_code = 500
    
    mock_response_200 = Mock()
    mock_response_200.status_code = 200
    mock_response_200.json.return_value = {"product": mock_product_data}
    
    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=[mock_response_500, mock_response_200]
        )
        
        result = await service._fetch_from_api_with_retry("BTC-USD", max_retries=3)
        
        assert result.success is True
        assert result.data == mock_product_data


def test_get_from_cache_with_ttl(service):
    """Test cache retrieval with TTL filter."""
    mock_row = {
        "product_id": "BTC-USD",
        "base_currency": "BTC",
        "updated_at": "2024-01-01T12:00:00Z"
    }
    
    with patch('backend.services.market_metadata.get_conn') as mock_conn:
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = mock_row
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor
        
        result = service._get_from_cache("BTC-USD", max_age_hours=1)
        
        assert result == mock_row
        # Verify TTL filter was applied
        call_args = mock_cursor.execute.call_args[0]
        assert "datetime('now', '-1 hours')" in call_args[0]


def test_get_from_cache_no_ttl(service):
    """Test cache retrieval without TTL filter."""
    mock_row = {
        "product_id": "BTC-USD",
        "base_currency": "BTC",
        "updated_at": "2020-01-01T12:00:00Z"  # Very old
    }
    
    with patch('backend.services.market_metadata.get_conn') as mock_conn:
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = mock_row
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor
        
        result = service._get_from_cache("BTC-USD", max_age_hours=None)
        
        assert result == mock_row
        # Verify no TTL filter
        call_args = mock_cursor.execute.call_args[0]
        assert "datetime" not in call_args[0]


def test_save_to_cache(service, mock_product_data):
    """Test saving product data to cache."""
    with patch('backend.services.market_metadata.get_conn') as mock_conn:
        mock_cursor = Mock()
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor
        
        service._save_to_cache("BTC-USD", mock_product_data)
        
        # Verify INSERT OR REPLACE was called
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args[0]
        assert "INSERT OR REPLACE" in call_args[0]
        assert call_args[1][0] == "BTC-USD"


def test_get_cache_age_seconds(service):
    """Test cache age calculation."""
    from datetime import datetime, timedelta
    
    # Mock data with timestamp 1 hour ago
    one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    cached_data = {"updated_at": one_hour_ago}
    
    age = service._get_cache_age_seconds(cached_data)
    
    # Should be approximately 3600 seconds (1 hour)
    assert 3500 < age < 3700


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
