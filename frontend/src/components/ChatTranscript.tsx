import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import type { ChatMessage, PromptPreset } from '../types';
import ChartModal from './ChartModal';

interface Props {
  messages: ChatMessage[];
  isLoading: boolean;
  generatingChartIds?: Set<string>;
  onGenerateChart?: (messageId: string) => void;
  promptPresets?: PromptPreset[];
  onPresetSelect?: (preset: PromptPreset) => void;
}

function ChatTranscript({
  messages,
  isLoading,
  generatingChartIds,
  onGenerateChart,
  promptPresets = [],
  onPresetSelect,
}: Props) {
  const [activeChart, setActiveChart] = useState<string | null>(null);
  const [dismissedCharts, setDismissedCharts] = useState<Set<string>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

  const dismissChart = (id: string) =>
    setDismissedCharts((prev) => new Set(prev).add(id));

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, isLoading]);

  const renderChartArea = (message: ChatMessage) => {
    // A chart already exists → always shown via a button that opens the modal.
    if (message.chartHtml) {
      return (
        <button
          type="button"
          className="chart-open-btn"
          onClick={() => setActiveChart(message.chartHtml!)}
        >
          📊 Ver gráfica
        </button>
      );
    }

    const isGenerating = generatingChartIds?.has(message.id) ?? false;
    if (isGenerating) {
      return (
        <div className="chart-generating">
          <span className="chart-spinner" aria-hidden="true" />
          <span>
            Generando gráfica
            <span className="chart-dots" aria-hidden="true">
              <span>.</span>
              <span>.</span>
              <span>.</span>
            </span>
          </span>
        </div>
      );
    }

    if (message.chartError) {
      return (
        <div className="chart-ask-text chart-error">
          No se pudo generar una gráfica para esta respuesta.
        </div>
      );
    }

    // Ask mode: a chart is possible but not generated yet → offer to generate it.
    if (message.chartAvailable && !dismissedCharts.has(message.id)) {
      return (
        <div className="chart-ask">
          <span className="chart-ask-text">
            📊 Para esta respuesta puedo generar una gráfica. ¿Quieres que la genere?
          </span>
          <div className="chart-ask-actions">
            <button
              type="button"
              className="chart-open-btn"
              onClick={() => onGenerateChart?.(message.id)}
            >
              Sí
            </button>
            <button
              type="button"
              className="chart-dismiss-btn"
              onClick={() => dismissChart(message.id)}
            >
              No
            </button>
          </div>
        </div>
      );
    }

    return null;
  };

  return (
    <div className="chat-transcript" aria-live="polite" aria-busy={isLoading}>
      {activeChart ? <ChartModal html={activeChart} onClose={() => setActiveChart(null)} /> : null}
      {messages.length === 0 && !isLoading ? (
        <div className="chat-empty-state">
          <div className="empty-state-header">
            <div className="empty-state-icon">💬</div>
            <h2 className="empty-state-title">Welcome to H.A.R.V.E.Y.</h2>
            <p className="empty-state-description">
              Your AI assistant for pricing intelligence and optimal subscription recommendations.
            </p>
          </div>
          {promptPresets.length > 0 && onPresetSelect && (
            <div className="prompt-suggestions">
              {promptPresets.map((preset) => (
                <button
                  key={preset.id}
                  className="prompt-suggestion-card"
                  onClick={() => onPresetSelect(preset)}
                  type="button"
                >
                  <span className="prompt-suggestion-text">{preset.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      ) : null}
      {messages.map((message) => (
        <article key={message.id} className={`message message-${message.role}`}>
          <header>
            <span className="message-role">{message.role === 'user' ? 'You' : 'H.A.R.V.E.Y.'}</span>
            <time dateTime={message.createdAt}>{new Date(message.createdAt).toLocaleTimeString()}</time>
          </header>
          <div className="message-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
          {renderChartArea(message)}
          {message.metadata?.plan || message.metadata?.result ? (
            <details>
              <summary>View H.A.R.V.E.Y. context</summary>
              {message.metadata.plan ? (
                <>
                  <h4>Planner</h4>
                  <pre>{JSON.stringify(message.metadata.plan, null, 2)}</pre>
                </>
              ) : null}
              {message.metadata.result ? (
                <>
                  <h4>Result</h4>
                  <pre>{JSON.stringify(message.metadata.result, null, 2)}</pre>
                </>
              ) : null}
            </details>
          ) : null}
        </article>
      ))}
      {isLoading ? <div className="message message-assistant">Processing request...</div> : null}
      <div ref={bottomRef} />
    </div>
  );
}

export default ChatTranscript;
