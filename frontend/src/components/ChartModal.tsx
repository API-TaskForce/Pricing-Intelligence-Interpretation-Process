import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';

interface Props {
  html: string;
  onClose: () => void;
}

function ChartModal({ html, onClose }: Props) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    setBlobUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [html]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return createPortal(
    <div className="chart-modal-overlay" onClick={onClose}>
      <div className="chart-modal" onClick={(e) => e.stopPropagation()}>
        <button className="chart-modal-close" onClick={onClose} aria-label="Close chart">✕</button>
        {blobUrl ? (
          <iframe
            src={blobUrl}
            className="chart-modal-iframe"
            title="Capacity curve chart"
          />
        ) : null}
      </div>
    </div>,
    document.body
  );
}

export default ChartModal;
