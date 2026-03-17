import { ChangeEvent, FormEvent, useRef, useState } from "react";
import ContextManager from "./ContextManager";
import type { ContextInputType, ContextMode, PricingContextItem } from "../types";
import SearchPricings from "./SearchPricings";
import Modal from "./Modal";

interface Props {
  question: string;
  detectedPricingUrls: string[];
  contextItems: PricingContextItem[];
  isSubmitting: boolean;
  isSubmitDisabled: boolean;
  mode: ContextMode;
  onQuestionChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onFileSelect: (files: FileList | null) => void;
  onContextAdd: (input: ContextInputType) => void;
  onContextRemove: (id: string) => void;
  onSphereContextRemove: (sphereId: string) => void;
  onContextClear: () => void;
}

function ControlPanel({
  question,
  detectedPricingUrls,
  contextItems,
  isSubmitting,
  isSubmitDisabled,
  mode,
  onQuestionChange,
  onSubmit,
  onFileSelect,
  onContextAdd,
  onContextRemove,
  onSphereContextRemove,
  onContextClear,
}: Props) {
  const [showPricingModal, setPricingModal] = useState<boolean>(false);

  const handleQuestionChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    onQuestionChange(event.target.value);
  };

  const handleOpenModal = () => setPricingModal(true);
  const handleCloseModal = () => setPricingModal(false);

  // Separate file input refs so pricing YAMLs and datasheets can live
  // under distinct "Select files" buttons in "all" mode.
  const pricingFileRef = useRef<HTMLInputElement>(null);
  const datasheetFileRef = useRef<HTMLInputElement>(null);

  const handleChoosePricingFile = () => pricingFileRef.current?.click();
  const handleChooseDatasheetFile = () => datasheetFileRef.current?.click();

  // Which sections to show based on the active context mode.
  const showPricingSection = mode === "saas" || mode === "all";
  const showDatasheetSection = mode === "api" || mode === "all";

  // Section header label changes per mode so it's always descriptive.
  const addContextLabel =
    mode === "saas" ? "Add Pricing Context" :
    mode === "api"  ? "Add Datasheet Context" :
                      "Add Context";

  return (
    <>
      <form className="control-form" onSubmit={onSubmit}>
        <label>
          Question
          <textarea
            name="question"
            required
            rows={4}
            value={question}
            onChange={handleQuestionChange}
            placeholder={
              mode === "api"
                ? "How long to make 500 API calls with 100 req/day limit?"
                : "Which is the best available subscription for a team of five users?"
            }
          />
        </label>

        <ContextManager
          items={contextItems}
          detectedUrls={detectedPricingUrls}
          mode={mode}
          onAdd={onContextAdd}
          onRemove={onContextRemove}
          onClear={onContextClear}
        />

        <h3>{addContextLabel}</h3>

        <div className="pricing-actions">
          {/* ── SaaS pricing YAML upload (saas + all modes) ── */}
          {showPricingSection && (
            <section className="ipricing-upload">
              <input
                ref={pricingFileRef}
                style={{ display: "none" }}
                type="file"
                accept=".yaml,.yml"
                multiple
                onChange={(event: ChangeEvent<HTMLInputElement>) => {
                  onFileSelect(event.target.files ?? null);
                }}
              />
              <button
                type="button"
                className="ipricing-file-selector"
                onClick={handleChoosePricingFile}
              >
                Select files
              </button>
              <h3>Upload pricing YAML (optional)</h3>
              <p style={{ margin: "1em auto" }} className="help-text">
                Uploaded YAMLs appear in the context above so you can remove
                them at any time.
              </p>
            </section>
          )}

          {/* ── SPHERE iPricing search (saas + all modes only) ── */}
          {showPricingSection && (
            <section className="search-ipricings">
              <button
                type="button"
                className="context-add-url"
                onClick={handleOpenModal}
              >
                Search pricings
              </button>
              <h3>Add SPHERE iPricing (optional)</h3>
              <p style={{ margin: "1em auto" }} className="help-text">
                Add iPricings with our SPHERE integration (our iPricing
                repository).
              </p>
              <p style={{ margin: "1em auto" }} className="help-text">
                You can further customize the search if you type a pricing name
                in the search bar.
              </p>
              <Modal open={showPricingModal} onClose={handleCloseModal}>
                <SearchPricings
                  onContextAdd={onContextAdd}
                  onContextRemove={onSphereContextRemove}
                />
              </Modal>
            </section>
          )}

          {/* ── Datasheet YAML upload (api + all modes) ── */}
          {showDatasheetSection && (
            <section className="ipricing-upload">
              <input
                ref={datasheetFileRef}
                style={{ display: "none" }}
                type="file"
                accept=".yaml,.yml"
                multiple
                onChange={(event: ChangeEvent<HTMLInputElement>) => {
                  onFileSelect(event.target.files ?? null);
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
          )}
        </div>

        <div className="control-actions">
          <button type="submit" disabled={isSubmitDisabled}>
            {isSubmitting ? "Processing..." : "Ask"}
          </button>
        </div>
      </form>
    </>
  );
}

export default ControlPanel;
