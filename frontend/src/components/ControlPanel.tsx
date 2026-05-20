import { ChangeEvent, FormEvent, KeyboardEvent, useRef } from "react";
import ContextManager from "./ContextManager";
import type { ContextInputType, PricingContextItem } from "../types";

interface Props {
  question: string;
  contextItems: PricingContextItem[];
  isSubmitting: boolean;
  isSubmitDisabled: boolean;
  onQuestionChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onFileSelect: (files: FileList | null) => void;
  onContextAdd: (input: ContextInputType) => void;
  onContextRemove: (id: string) => void;
  onContextClear: () => void;
}

function ControlPanel({
  question,
  contextItems,
  isSubmitting,
  isSubmitDisabled,
  onQuestionChange,
  onSubmit,
  onFileSelect,
  onContextAdd,
  onContextRemove,
  onContextClear,
}: Props) {
  const datasheetFileRef = useRef<HTMLInputElement>(null);

  const handleChooseDatasheetFile = () => datasheetFileRef.current?.click();

  const handleQuestionChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    onQuestionChange(event.target.value);
  };

  const handleQuestionKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      const target = event.currentTarget;
      const start = target.selectionStart ?? 0;
      const end = target.selectionEnd ?? 0;
      const newValue = target.value.substring(0, start) + "\n" + target.value.substring(end);
      onQuestionChange(newValue);
      setTimeout(() => {
        target.selectionStart = start + 1;
        target.selectionEnd = start + 1;
      }, 0);
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
          onChange={handleQuestionChange}
          onKeyDown={handleQuestionKeyDown}
          placeholder="How long to make 500 API calls with 100 req/day limit?"
        />
      </label>

      <ContextManager
        items={contextItems}
        onAdd={onContextAdd}
        onRemove={onContextRemove}
        onClear={onContextClear}
      />

      <h3>Add Datasheet Context</h3>

      <div className="pricing-actions">
        <section className="ipricing-upload">
          <input
            ref={datasheetFileRef}
            style={{ display: "none" }}
            type="file"
            accept=".yaml,.yml"
            multiple
            onChange={(event: ChangeEvent<HTMLInputElement>) => {
              onFileSelect(event.target.files ?? null);
              event.target.value = "";
            }}
          />
          <button
            type="button"
            className="ipricing-file-selector"
            onClick={handleChooseDatasheetFile}
          >
            Select files
          </button>
          <h3>Upload Datasheet YAML (optional)</h3>
          <p style={{ margin: "1em auto" }} className="help-text">
            Upload an API Datasheet YAML so H.A.R.V.E.Y. can evaluate rate
            limits and quotas for a specific plan.
          </p>
        </section>
      </div>

      <div className="control-actions">
        <button type="submit" disabled={isSubmitDisabled}>
          {isSubmitting ? "Processing..." : "Ask"}
        </button>
      </div>
    </form>
  );
}

export default ControlPanel;
