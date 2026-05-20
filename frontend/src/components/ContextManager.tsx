import { useState } from "react";

import type { ContextInputType, PricingContextItem } from "../types";
import ContextManagerItem from "./ContextManagerItem";

interface Props {
  items: PricingContextItem[];
  onAdd: (input: ContextInputType) => void;
  onRemove: (id: string) => void;
  onClear: () => void;
}

function ContextManager({ items, onAdd, onRemove, onClear }: Props) {
  const [error, setError] = useState<string | null>(null);

  return (
    <section className="context-manager">
      <header className="context-manager-header">
        <div>
          <h3>Datasheet Context</h3>
          <p className="context-subtitle">Upload Datasheet YAMLs to ground API analysis.</p>
        </div>
        <div className="context-controls">
          <span className="context-count">{items.length} selected</span>
          {items.length > 0 ? (
            <button type="button" className="context-clear" onClick={onClear}>
              Clear all
            </button>
          ) : null}
        </div>
      </header>

      <div className="context-list">
        {items.length === 0 ? (
          <p className="context-empty">
            No datasheet selected. Upload one to ground API analysis.
          </p>
        ) : (
          <ul>
            {items.map((item) => (
              <ContextManagerItem key={item.id} item={item} onRemove={onRemove} />
            ))}
          </ul>
        )}
      </div>

      {error ? <p className="context-error">{error}</p> : null}
    </section>
  );
}

export default ContextManager;
