"""Tests for Pushover notification service."""
import pytest
from unittest.mock import patch, MagicMock
from backend.services.notifications.pushover import (
    send_pushover,
    notify_trade_placed,
    notify_trade_failed,
    notify_pending_confirmation
)


@pytest.fixture
def mock_settings():
    """Mock settings with Pushover enabled."""
    with patch('backend.services.notifications.pushover.get_settings') as mock:
        settings = MagicMock()
        settings.pushover_enabled = True
        settings.pushover_app_token = "test_app_token"
        settings.pushover_user_key = "test_user_key"
        mock.return_value = settings
        yield settings


@pytest.fixture
def mock_db():
    """Mock database connection."""
    with patch('backend.services.notifications.pushover.get_conn') as mock:
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        conn.__enter__.return_value = conn
        conn.__exit__.return_value = None
        mock.return_value = conn
        yield conn


class TestPushoverSender:
    """Test Pushover notification sender."""
    
    @patch('backend.services.notifications.pushover.requests.post')
    def test_send_pushover_success(self, mock_post, mock_settings, mock_db):
        """Test successful notification send."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        result = send_pushover(
            message="Test message",
            title="Test Title",
            run_id="run_test"
        )
        
        assert result is True
        assert mock_post.called
        call_args = mock_post.call_args
        assert call_args[1]['data']['message'] == "Test message"
        assert call_args[1]['data']['title'] == "Test Title"
        assert call_args[1]['timeout'] == 5
    
    @patch('backend.services.notifications.pushover.requests.post')
    def test_send_pushover_retry_on_failure(self, mock_post, mock_settings, mock_db):
        """Test retry logic on failure."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server error"
        mock_post.return_value = mock_response
        
        result = send_pushover(message="Test", title="Test")
        
        assert result is False
        assert mock_post.call_count == 2  # MAX_RETRIES
    
    @patch('backend.services.notifications.pushover.requests.post')
    def test_send_pushover_disabled(self, mock_post, mock_db):
        """Test notification when Pushover is disabled."""
        with patch('backend.services.notifications.pushover.get_settings') as mock:
            settings = MagicMock()
            settings.pushover_enabled = False
            mock.return_value = settings
            
            result = send_pushover(message="Test", title="Test")
            
            assert result is False
            assert not mock_post.called
    
    @patch('backend.services.notifications.pushover.requests.post')
    def test_send_pushover_missing_credentials(self, mock_post, mock_db):
        """Test notification with missing credentials."""
        with patch('backend.services.notifications.pushover.get_settings') as mock:
            settings = MagicMock()
            settings.pushover_enabled = True
            settings.pushover_app_token = None
            settings.pushover_user_key = None
            mock.return_value = settings
            
            result = send_pushover(message="Test", title="Test")
            
            assert result is False
            assert not mock_post.called


class TestTradeNotifications:
    """Test trade-specific notification helpers."""
    
    @patch('backend.services.notifications.pushover.send_pushover')
    def test_notify_trade_placed_live(self, mock_send):
        """Test LIVE trade placement notification."""
        mock_send.return_value = True
        
        result = notify_trade_placed(
            mode="LIVE",
            side="buy",
            symbol="BTC-USD",
            notional_usd=10.0,
            order_id="ord_123",
            run_id="run_test"
        )
        
        assert result is True
        assert mock_send.called
        call_args = mock_send.call_args[1]
        assert "LIVE" in call_args['title']
        assert "⚠️" in call_args['title']
        assert call_args['priority'] == 1
    
    @patch('backend.services.notifications.pushover.send_pushover')
    def test_notify_trade_placed_paper(self, mock_send):
        """Test PAPER trade placement notification."""
        mock_send.return_value = True
        
        result = notify_trade_placed(
            mode="PAPER",
            side="sell",
            symbol="ETH-USD",
            notional_usd=20.0,
            order_id="ord_456"
        )
        
        assert result is True
        assert mock_send.called
        call_args = mock_send.call_args[1]
        assert "PAPER" in call_args['title']
        assert "📄" in call_args['title']
        assert call_args['priority'] == 0
    
    @patch('backend.services.notifications.pushover.send_pushover')
    def test_notify_trade_failed(self, mock_send):
        """Test trade failure notification."""
        mock_send.return_value = True
        
        result = notify_trade_failed(
            mode="LIVE",
            symbol="BTC-USD",
            notional_usd=10.0,
            error="Insufficient funds",
            run_id="run_test"
        )
        
        assert result is True
        assert mock_send.called
        call_args = mock_send.call_args[1]
        assert "Failed" in call_args['title']
        assert "❌" in call_args['title']
        assert "Insufficient funds" in call_args['message']
    
    @patch('backend.services.notifications.pushover.send_pushover')
    def test_notify_pending_confirmation(self, mock_send):
        """Test pending confirmation notification."""
        mock_send.return_value = True
        
        result = notify_pending_confirmation(
            mode="LIVE",
            side="buy",
            symbol="BTC-USD",
            notional_usd=10.0,
            conversation_id="conv_test"
        )
        
        assert result is True
        assert mock_send.called
        call_args = mock_send.call_args[1]
        assert "Pending" in call_args['title']
        assert "CONFIRM" in call_args['message']
