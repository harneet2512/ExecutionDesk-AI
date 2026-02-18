'use client';

import { useState, useEffect } from 'react';
import { listRunTelemetry, type RunTelemetry } from '@/lib/api';

export default function TelemetryList() {
    const [telemetry, setTelemetry] = useState<RunTelemetry[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        loadTelemetry();
    }, []);

    const loadTelemetry = async () => {
        try {
            setLoading(true);
            const tel = await listRunTelemetry();
            setTelemetry(tel);
        } catch (e) {
            console.error('Failed to load telemetry:', e);
        } finally {
            setLoading(false);
        }
    };

    if (loading) {
        return (
            <div className="p-4 space-y-3">
                {[1, 2, 3].map((i) => (
                    <div key={i} className="h-24 theme-elevated rounded-lg animate-pulse" />
                ))}
            </div>
        );
    }

    return (
        <div className="p-3 space-y-2">
            {telemetry.length === 0 ? (
                <p className="text-sm theme-text-secondary text-center py-8">
                    No telemetry data yet.
                </p>
            ) : (
                telemetry.map((tel) => (
                    <div
                        key={tel.run_id}
                        className="p-3 theme-surface rounded-lg border theme-border shadow-sm"
                    >
                        <div className="text-xs font-mono theme-text-secondary truncate mb-2">
                            {tel.run_id}
                        </div>
                        <div className="grid grid-cols-2 gap-2 text-xs">
                            <div className="flex items-center justify-between">
                                <span className="theme-text-secondary">Tools:</span>
                                <span className="font-medium theme-text">{tel.tool_calls_count}</span>
                            </div>
                            <div className="flex items-center justify-between">
                                <span className="theme-text-secondary">Events:</span>
                                <span className="font-medium theme-text">{tel.sse_events_count}</span>
                            </div>
                            <div className="flex items-center justify-between">
                                <span className="theme-text-secondary">Errors:</span>
                                <span className={`font-medium ${tel.error_count > 0 ? 'text-[var(--color-status-error)]' : 'theme-text'}`}>
                                    {tel.error_count}
                                </span>
                            </div>
                            {tel.duration_ms && (
                                <div className="flex items-center justify-between">
                                    <span className="theme-text-secondary">Duration:</span>
                                    <span className="font-medium theme-text">{tel.duration_ms}ms</span>
                                </div>
                            )}
                        </div>
                    </div>
                ))
            )}
        </div>
    );
}
