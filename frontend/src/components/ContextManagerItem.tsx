import { DatasheetContextItem } from "../types";
import TrashIcon from "./TrashIcon";

interface Props {
  item: DatasheetContextItem;
  onRemove: (id: string) => void;
  locked?: boolean;
}

function originLabel(origin?: string): string {
  switch (origin) {
    case "user":   return "Manual";
    case "preset": return "Preset";
    default:       return "";
  }
}

function ContextManagerItem({ item, onRemove, locked }: Props) {
  const kindLabel = item.kind === "yaml-url" ? "URL" : "YAML";
  const meta = `${kindLabel} · ${originLabel(item.origin)}`.trim().replace(/·\s*$/, "");

  return (
    <li className="context-item">
      <div className="context-item-info">
        <span className="context-item-label">{item.label}</span>
        <span className="context-item-meta">{meta}</span>
      </div>
      <div className="context-item-actions">
        {item.kind === "yaml-url" && (
          <a
            href={item.value}
            target="_blank"
            rel="noopener noreferrer"
            className="context-view-btn"
            title="View raw datasheet"
          >
            View
          </a>
        )}
        {!locked && (
          <button
            type="button"
            className="context-remove"
            onClick={() => onRemove(item.id)}
          >
            <TrashIcon width={24} height={24} />
          </button>
        )}
      </div>
    </li>
  );
}

export default ContextManagerItem;
