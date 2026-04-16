import type { ContextInputType, DatasheetContextItem } from "../types";
import ContextManagerItem from "./ContextManagerItem";

interface Props {
  items: DatasheetContextItem[];
  onAdd: (input: ContextInputType) => void;
  onRemove: (id: string) => void;
  onClear: () => void;
}

function ContextManager({ items, onRemove, onClear }: Props) {
  return (
    <section className="context-manager">
      <header className="context-manager-header">
        <div>
          <h3>Datasheet Context</h3>
          <p className="context-subtitle">
            Upload Datasheet YAMLs to ground API analysis.
          </p>
        </div>
        <div className="context-controls">
          <span className="context-count">{items.length} selected</span>
          {items.length > 0 && (
            <button type="button" className="context-clear" onClick={onClear}>
              Clear all
            </button>
          )}
        </div>
      </header>

      <div className="context-list">
        {items.length === 0 ? (
          <p className="context-empty">
            No datasheet loaded. Upload a YAML to ground H.A.R.V.E.Y.'s analysis.
          </p>
        ) : (
          <ul>
            {items.map((item) => (
              <ContextManagerItem key={item.id} item={item} onRemove={onRemove} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

export default ContextManager;
