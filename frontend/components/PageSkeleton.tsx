'use client';

interface PageSkeletonProps {
  title?: string;
  rows?: number;
}

export default function PageSkeleton({ title, rows = 4 }: PageSkeletonProps) {
  return (
    <div className="p-8 max-w-7xl mx-auto animate-pulse">
      {title && (
        <div className="h-8 w-48 theme-elevated rounded mb-6" />
      )}
      {!title && (
        <div className="h-8 w-64 theme-elevated rounded mb-6" />
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 theme-elevated rounded-lg" />
        ))}
      </div>

      <div className="space-y-3">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="h-12 theme-elevated rounded-lg" />
        ))}
      </div>
    </div>
  );
}
