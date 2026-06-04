import { useEffect, useState } from 'react';

interface Props {
  html: string;
  onExpand: () => void;
}

function ChartInline({ html, onExpand }: Props) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    setBlobUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [html]);

  return (
    <div className="chart-inline">
      <div className="chart-inline-toolbar">
        <span className="chart-inline-label">📊 Gráfica de curva de capacidad</span>
        <button type="button" className="chart-expand-btn" onClick={onExpand}>
          ⤢ Ampliar
        </button>
      </div>
      {blobUrl ? (
        <iframe src={blobUrl} className="chart-inline-iframe" title="Capacity curve chart" />
      ) : null}
    </div>
  );
}

export default ChartInline;
