/**
 * Browser-ready WebSocket client for Polymarket market data.
 *
 * Demonstrates:
 * - Connecting to the Polymarket CLOB WebSocket
 * - Subscribing to price and book channels
 * - Auto-reconnect with exponential backoff
 * - No authentication required for read-only streams
 *
 * Usage (Node.js):
 *   npx ts-node websocket_client.ts <token_id>
 *
 * Usage (Browser):
 *   import { PolymarketWS } from './websocket_client';
 *   const ws = new PolymarketWS();
 *   ws.subscribe('book', tokenId, (data) => console.log(data));
 */

const WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market";

type MessageHandler = (data: Record<string, unknown>) => void;

interface Subscription {
  channel: string;
  tokenId: string;
  handler: MessageHandler;
}

class PolymarketWS {
  private ws: WebSocket | null = null;
  private subscriptions: Subscription[] = [];
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(WS_URL);

      this.ws.onopen = () => {
        console.log("[PolymarketWS] Connected");
        this.reconnectAttempts = 0;
        // Re-subscribe after reconnect
        for (const sub of this.subscriptions) {
          this.sendSubscribe(sub.channel, sub.tokenId);
        }
        resolve();
      };

      this.ws.onmessage = (event) => {
        const msg = JSON.parse(event.data as string);
        const channel = msg.type || msg.channel;
        for (const sub of this.subscriptions) {
          if (sub.channel === channel) {
            sub.handler(msg);
          }
        }
      };

      this.ws.onclose = () => {
        console.log("[PolymarketWS] Disconnected");
        this.attemptReconnect();
      };

      this.ws.onerror = (err) => {
        console.error("[PolymarketWS] Error:", err);
        reject(err);
      };
    });
  }

  subscribe(channel: string, tokenId: string, handler: MessageHandler): void {
    this.subscriptions.push({ channel, tokenId, handler });
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.sendSubscribe(channel, tokenId);
    }
  }

  private sendSubscribe(channel: string, tokenId: string): void {
    this.ws?.send(
      JSON.stringify({
        type: "subscribe",
        channel,
        assets_ids: [tokenId],
      })
    );
  }

  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error("[PolymarketWS] Max reconnect attempts reached");
      return;
    }
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
    this.reconnectAttempts++;
    console.log(`[PolymarketWS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    setTimeout(() => this.connect(), delay);
  }

  disconnect(): void {
    this.subscriptions = [];
    this.ws?.close();
  }
}

// CLI usage
if (typeof process !== "undefined" && process.argv?.length > 2) {
  const tokenId = process.argv[2];
  const client = new PolymarketWS();

  client.subscribe("book", tokenId, (data: Record<string, unknown>) => {
    const bids = data.bids as Array<{ price: string; size: string }> | undefined;
    const asks = data.asks as Array<{ price: string; size: string }> | undefined;
    if (bids?.length && asks?.length) {
      const bestBid = parseFloat(bids[0].price);
      const bestAsk = parseFloat(asks[0].price);
      const spread = (bestAsk - bestBid).toFixed(4);
      console.log(`Bid: ${bestBid.toFixed(2)}  Ask: ${bestAsk.toFixed(2)}  Spread: ${spread}`);
    }
  });

  client.connect().catch(console.error);
}

export { PolymarketWS };
