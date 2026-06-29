'use client';

import { useState } from 'react';
import { ClientIssue, ClientIssueComment, updateClientIssue } from '@/lib/api';

interface IssueThreadProps {
  issue: ClientIssue;
  tenantId: string;
  onUpdate?: (updated: ClientIssue) => void;
}

const STATUS_COLORS: Record<string, string> = {
  open: 'var(--color-status-warning)',
  in_progress: 'var(--chart-2)',
  resolved: 'var(--color-status-success)',
  closed: 'var(--chart-3)',
};

const PRIORITY_LABELS: Record<string, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
};

export default function IssueThread({ issue, tenantId, onUpdate }: IssueThreadProps) {
  const [commentText, setCommentText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [localIssue, setLocalIssue] = useState(issue);
  const [localComments, setLocalComments] = useState<ClientIssueComment[]>(issue.comments || []);

  const handleAddComment = async () => {
    if (!commentText.trim()) return;
    setSubmitting(true);
    try {
      const updated = await updateClientIssue(tenantId, localIssue.issue_id, {
        comment: commentText.trim(),
      });
      setLocalComments(updated.comments || []);
      setCommentText('');
      onUpdate?.(updated);
    } catch {
      // Silently handle error
    } finally {
      setSubmitting(false);
    }
  };

  const handleStatusChange = async (newStatus: string) => {
    try {
      const updated = await updateClientIssue(tenantId, localIssue.issue_id, {
        status: newStatus,
      });
      setLocalIssue(updated);
      setLocalComments(updated.comments || []);
      onUpdate?.(updated);
    } catch {
      // Silently handle error
    }
  };

  return (
    <div className="theme-elevated border theme-border rounded-xl overflow-hidden">
      {/* Issue header */}
      <div className="p-4 border-b theme-border">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-lg font-semibold theme-text">{localIssue.title}</h3>
            {localIssue.description && (
              <p className="text-sm theme-text-secondary mt-1">{localIssue.description}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span
              className="text-xs font-medium px-2 py-1 rounded-full"
              style={{
                color: STATUS_COLORS[localIssue.status] || 'var(--chart-3)',
                backgroundColor: 'var(--color-fill-ghost-hover)',
              }}
            >
              {localIssue.status}
            </span>
            <span className="text-xs theme-text-secondary">
              {PRIORITY_LABELS[localIssue.priority] || localIssue.priority}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-4 mt-3 text-xs theme-text-secondary">
          <span>Created: {new Date(localIssue.created_at).toLocaleString()}</span>
          {localIssue.assigned_to && <span>Assigned: {localIssue.assigned_to}</span>}
          {localIssue.resolved_at && <span>Resolved: {new Date(localIssue.resolved_at).toLocaleString()}</span>}
        </div>
        {/* Status actions */}
        {localIssue.status !== 'resolved' && localIssue.status !== 'closed' && (
          <div className="flex gap-2 mt-3">
            {localIssue.status === 'open' && (
              <button
                onClick={() => handleStatusChange('in_progress')}
                className="btn-secondary text-xs"
              >
                Start Progress
              </button>
            )}
            <button
              onClick={() => handleStatusChange('resolved')}
              className="btn-primary text-xs"
            >
              Resolve
            </button>
          </div>
        )}
      </div>

      {/* Comments thread */}
      <div className="divide-y theme-border">
        {localComments.map((comment) => (
          <div key={comment.comment_id} className="p-4">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm font-medium theme-text">{comment.author}</span>
              <span className="text-xs theme-text-secondary">
                {new Date(comment.created_at).toLocaleString()}
              </span>
            </div>
            <p className="text-sm theme-text-secondary">{comment.content}</p>
          </div>
        ))}
        {localComments.length === 0 && (
          <div className="p-4 text-sm theme-text-secondary text-center">
            No comments yet.
          </div>
        )}
      </div>

      {/* Add comment */}
      <div className="p-4 border-t theme-border">
        <div className="flex gap-2">
          <input
            type="text"
            value={commentText}
            onChange={(e) => setCommentText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleAddComment(); }}}
            placeholder="Add a comment..."
            className="flex-1 px-3 py-2 text-sm theme-elevated border theme-border rounded-lg theme-text placeholder:theme-text-secondary"
          />
          <button
            onClick={handleAddComment}
            disabled={submitting || !commentText.trim()}
            className="btn-primary text-sm"
          >
            {submitting ? 'Sending...' : 'Comment'}
          </button>
        </div>
      </div>
    </div>
  );
}
