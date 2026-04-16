import { DatasheetContextItem } from "../types";
import TrashIcon from "./TrashIcon";

interface Props {
  item: DatasheetContextItem;
  onRemove: (id: string) => void;
}

function originLabel(origin?: string): string {
  switch (origin) {
    case "user":   return "Manual";
    case "preset": return "Preset";
    default:       return "";
  }
}

function ContextManagerItem({ item, onRemove }: Props) {
  const meta = `YAML · ${originLabel(item.origin)}`.trim().replace(/·\s*$/, "");

  return (
    <li className="context-item">
      <div>
        <span className="context-item-label">{item.label}</span>
        <span className="context-item-meta">{meta}</span>
      </div>
      <button
        type="button"
        className="context-remove"
        onClick={() => onRemove(item.id)}
      >
        <TrashIcon width={24} height={24} />
      </button>
    </li>
  );
}

export default ContextManagerItem;
