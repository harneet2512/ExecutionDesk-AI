'use client';

import { useState, useEffect } from 'react';
import { apiFetchSafe } from '@/lib/api';

interface RunSummaryProps {
  runId: string;
}

export default function RunSummary({ runId }: RunSummaryProps) {
  const [summary, setSummary] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchSummary() {
      try {
        const trace = await apiFetchSafe(`/api/v1/runs/${runId}/trace`);
        if (!trace) {
          setSummary(null);
          return;
        }

        const rankings = trace.artifacts?.rankings || [];
        const proposal = trace.plan?.selected_order || {};

        // Trade runs: use rankings and selected order
        if (rankings.length > 0 && proposal.symbol) {
          const topRank = rankings[0];
          let summaryText = `Selected ${proposal.symbol} based on ${((topRank.return_24h || topRank.score || 0) * 100).toFixed(2)}% return over lookback window. Executed order: ${proposal.side} $${typeof proposal.notional_usd === 'number' ? proposal.notional_usd.toFixed(2) : '\u2014'} via ${trace.run?.execution_mode || '\u2014'} mode.`;

          if (trace.run?.execution_mode === 'REPLAY') {
            summaryText += " [REPLAY DETERMINISTIC: ON]";
          }
          setSummary(summaryText);
          return;
        }

        // Portfolio runs: check for portfolio_brief in metadata or recent events
        const recentEvents = trace.recent_events || [];
        for (const event of recentEvents) {
          if (event.payload?.portfolio_brief) {
            const brief = event.payload.portfolio_brief;
            const totalValue = brief.total_value_usd || 0;
            const holdings = brief.holdings?.length || 0;
            setSummary(`Portfolio: $${totalValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} total value, ${holdings} holding(s)`);
            return;
          }
        }

        // No applicable artifacts - return null (component will render nothing)
        setSummary(null);
      } catch (e) {
        console.error('Summary generation failed:', e);
        setSummary(null);
      } finally {
        setLoading(false);
      }
    }

    if (runId) {
      fetchSummary();
    }
  }, [runId]);

  // Show nothing while loading or if no summary available
  if (loading || !summary) {
    return null;
  }

  return <p className="text-xs theme-text-secondary">{summary}</p>;
}

