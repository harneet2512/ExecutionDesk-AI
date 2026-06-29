'use client';

import { useRef, useState, useEffect, type ReactElement } from 'react';

interface ChartBoxProps {
  height?: number;
  children: (width: number, height: number) => ReactElement;
}

export default function ChartBox({ height = 220, children }: ChartBoxProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(400);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setW(el.clientWidth || 400);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={ref} style={{ width: '100%', height }}>
      {children(w, height)}
    </div>
  );
}
