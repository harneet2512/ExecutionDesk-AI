import pytest
from unittest.mock import Mock, AsyncMock, patch
from backend.services.news_ingestion import NewsIngestionService
from backend.providers.news import RSSProvider, GDELTProvider

@pytest.fixture
def mock_rss():
    with patch("backend.services.news_ingestion.RSSProvider") as m:
        provider = AsyncMock()
        m.return_value = provider
        yield provider

@pytest.fixture
def mock_gdelt():
    with patch("backend.services.news_ingestion.GDELTProvider") as m:
        provider = AsyncMock()
        m.return_value = provider
        yield provider

@pytest.mark.asyncio
async def test_ingest_rss_source(mock_rss, mock_gdelt):
    # Setup service with mocked providers
    service = NewsIngestionService()
    service.rss_provider = mock_rss
    service.gdelt_provider = mock_gdelt
    
    # Mock enabled sources
    with patch.object(service, "_get_enabled_sources") as mock_get_sources:
        mock_get_sources.return_value = [
            {"id": "source_1", "type": "rss", "url": "http://test.com/feed", "is_enabled": 1}
        ]
        
        # Mock fetch result
        mock_rss.fetch.return_value = [
            {
                "source_id": "source_1",
                "title": "Bitcoin reaches ATH", 
                "url": "http://test.com/1", 
                "canonical_url": "http://test.com/1",
                "published_at": "2024-01-01T12:00:00Z",
                "content_hash": "hash1",
                "summary": "BTC up",
                "raw_payload_json": "{}",
                "lang": "en"
            }
        ]
        
        # Mock save items to avoid DB calls
        with patch.object(service, "_save_items") as mock_save:
            mock_save.return_value = 1
            
            # Run
            await service.ingest_all()
            
            # Verify
            mock_rss.fetch.assert_called_once_with("source_1", "http://test.com/feed")
            mock_save.assert_called_once()
            args, _ = mock_save.call_args
            assert args[0][0]["title"] == "Bitcoin reaches ATH"

@pytest.mark.asyncio
async def test_manual_mapping():
    # Test asset mapping logic (extracting assets)
    # We can test NewsMappingService separately or via IngestionService integration
    from backend.services.news_mapping import NewsMappingService
    mapper = NewsMappingService()
    
    mentions = mapper.extract_assets("Bitcoin (BTC) is up. Ethereum is down.")
    symbols = {m["asset_symbol"] for m in mentions}
    assert "BTC" in symbols
    assert "ETH" in symbols
