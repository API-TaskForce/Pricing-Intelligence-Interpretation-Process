import { ChangeEvent, DragEvent, FormEvent, useRef, useState } from "react";
import ContextManager from "./ContextManager";
import type { ContextInputType, DatasheetContextItem } from "../types";

interface Props {
  question: string;
  contextItems: DatasheetContextItem[];
  isSubmitting: boolean;
  isSubmitDisabled: boolean;
  lockContext?: boolean;
  onQuestionChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onFileSelect: (files: FileList | null) => void;
  onContextAdd: (input: ContextInputType) => void;
  onContextRemove: (id: string) => void;
  onContextClear: () => void;
}

function isValidUrl(value: string): boolean {
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function ControlPanel({
  question,
  contextItems,
  isSubmitting,
  isSubmitDisabled,
  lockContext,
  onQuestionChange,
  onSubmit,
  onFileSelect,
  onContextAdd,
  onContextRemove,
  onContextClear,
}: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [urlInput, setUrlInput] = useState("");
  const [urlError, setUrlError] = useState("");

  const handleDragOver = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    if (files && files.length > 0) onFileSelect(files);
  };

  const handleAddUrl = () => {
    const trimmed = urlInput.trim();
    if (!trimmed) return;
    if (!isValidUrl(trimmed)) {
      setUrlError("Enter a valid http/https URL.");
      return;
    }
    const label = trimmed.split("/").filter(Boolean).pop() ?? trimmed;
    onContextAdd({ kind: "yaml-url", label, value: trimmed, origin: "user" });
    setUrlInput("");
    setUrlError("");
  };

  const handleUrlKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddUrl();
    }
  };

  return (
    <form className="control-form" onSubmit={onSubmit}>
      <label>
        Question
        <textarea
          name="question"
          required
          rows={4}
          value={question}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => onQuestionChange(e.target.value)}
          placeholder="How long to make 500 API calls with 100 req/day limit?"
        />
      </label>

      <ContextManager
        items={contextItems}
        onAdd={onContextAdd}
        onRemove={onContextRemove}
        onClear={onContextClear}
        locked={lockContext}
      />

      {!lockContext && (
        <div className="datasheet-adder">
          <p className="datasheet-adder-title">Add Datasheet</p>

          {/* Drop zone */}
          <label
            className={`drop-zone${isDragging ? " drop-zone--active" : ""}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".yaml,.yml"
              multiple
              style={{ display: "none" }}
              onChange={(e: ChangeEvent<HTMLInputElement>) => onFileSelect(e.target.files ?? null)}
            />
            <span className="drop-zone-icon">📄</span>
            <span className="drop-zone-text">
              {isDragging ? "Drop to add" : "Drag & drop a YAML file"}
            </span>
            <span className="drop-zone-or">or</span>
            <span
              className="drop-zone-btn"
              onClick={(e) => { e.preventDefault(); fileRef.current?.click(); }}
            >
              Browse files
            </span>
          </label>

          {/* Divider */}
          <div className="adder-divider"><span>or add by URL</span></div>

          {/* URL row */}
          <div className="url-row">
            <input
              type="text"
              className={`url-row-input${urlError ? " url-row-input--error" : ""}`}
              placeholder="https://example.com/datasheet.yaml"
              value={urlInput}
              onChange={(e) => { setUrlInput(e.target.value); setUrlError(""); }}
              onKeyDown={handleUrlKeyDown}
            />
            <button
              type="button"
              className="url-row-btn"
              onClick={handleAddUrl}
              disabled={!urlInput.trim()}
            >
              Add
            </button>
          </div>
          {urlError && <p className="url-row-error">{urlError}</p>}
        </div>
      )}

      <div className="control-actions">
        <button type="submit" disabled={isSubmitDisabled}>
          {isSubmitting ? "Processing..." : "Ask"}
        </button>
      </div>
    </form>
  );
}

export default ControlPanel;
