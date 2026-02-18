'use client';

import { NavSection } from './AppShell';
import ConversationList from './ConversationList';
import RunsList from './RunsList';
import TelemetryList from './TelemetryList';
import EvalSidebarList from './EvalSidebarList';

interface ResizableSidebarPanelProps {
    activeSection: NavSection;
}

export default function ResizableSidebarPanel({
    activeSection,
}: ResizableSidebarPanelProps) {
    const sectionTitles: Record<NavSection, string> = {
        chats: 'Conversations',
        trades: 'Trading Runs',
        evals: 'Evaluations',
        telemetry: 'Telemetry',
        ops: 'Operations',
    };

    return (
        <div className="w-80 theme-bg border-r theme-border flex flex-col overflow-hidden flex-shrink-0">
            {/* Sidebar Header */}
            <div className="p-4 border-b theme-border">
                <h2 className="text-sm font-semibold theme-text uppercase tracking-wide">
                    {sectionTitles[activeSection]}
                </h2>
            </div>

            {/* Sidebar Content */}
            <div className="flex-1 overflow-y-auto">
                {activeSection === 'chats' && <ConversationList />}
                {activeSection === 'trades' && <RunsList />}
                {activeSection === 'evals' && <EvalSidebarList />}
                {activeSection === 'telemetry' && <TelemetryList />}
                {activeSection === 'ops' && (
                    <div className="p-4 text-sm theme-text-secondary text-center">
                        Operations dashboard coming soon.
                    </div>
                )}
            </div>
        </div>
    );
}
