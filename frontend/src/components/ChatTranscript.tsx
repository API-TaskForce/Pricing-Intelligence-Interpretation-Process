import { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import type { ChatMessage, PromptPreset } from '../types';

interface Props {
  messages: ChatMessage[];
  isLoading: boolean;
  promptPresets?: PromptPreset[];
  onPresetSelect?: (preset: PromptPreset) => void;
}

function ChatTranscript({ messages, isLoading, promptPresets = [], onPresetSelect }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, isLoading]);

  return (
    <div className="chat-transcript" aria-live="polite" aria-busy={isLoading}>
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
