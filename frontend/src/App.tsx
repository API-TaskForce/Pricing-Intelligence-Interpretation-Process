import { FormEvent, useEffect, useState } from "react";

import ChatTranscript from "./components/ChatTranscript";
import ControlPanel from "./components/ControlPanel";
import DemoPresetPanel from "./components/DemoPresetPanel";
import LoginPage from "./components/LoginPage";
import ApiKeySetup from "./components/ApiKeySetup";
import ModeNav, { MODES } from "./components/ModeNav";
import ModeSettingsButton from "./components/ModeSettingsButton";
import type {
  ChatMessage,
  DatasheetContextItem,
  HarveyMode,
  PromptPreset,
  ContextInputType,
  ChatRequest,
} from "./types";
import { SENDGRID_PRESETS } from "./prompts";
import { ThemeContext, ThemeType } from "./context/themeContext";
import {
  chatWithAgent,
  buildChatPayload,
  deleteDatasheet,
  uploadDatasheet,
} from "./utils";
import { PricingContext } from "./context/pricingContext";
import { useAuth } from "./context/authContext";
import {
  MAILERSEND_URL,
  PEERTUBE_URL,
  DAILYMOTION_URL,
  SENDGRID_2025_URL,
  SENDGRID_2026_URL,
} from "./datasheets";

const MODE_DATASHEET: Record<HarveyMode, { label: string; url: string }> = {
  "sendgrid-2025": { label: "Sendgrid@RAPIDAPI_datasheet-2025.yaml", url: SENDGRID_2025_URL },
  "sendgrid-2026": { label: "Sendgrid@RAPIDAPI_datasheet-2026.yaml", url: SENDGRID_2026_URL },
  mailersend: { label: "mailersend_v03.yaml", url: MAILERSEND_URL },
  peertube: { label: "peertube_v03.yaml", url: PEERTUBE_URL },
  dailymotion: { label: "dailymotion_v03.yaml", url: DAILYMOTION_URL },
};

const MODE_PRESETS: Partial<Record<HarveyMode, PromptPreset[]>> = {
  "sendgrid-2025": SENDGRID_PRESETS,
  "sendgrid-2026": SENDGRID_PRESETS,
};

const DEMO_FALLBACK_RESPONSE =
  "Esta es una respuesta de demostración. Inicia sesión para obtener respuestas en tiempo real del agente H.A.R.V.E.Y.";

const initTheme = (): ThemeType => {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem("pricing-theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
};

interface AppContentProps {
  isDemo: boolean;
  onLoginClick: () => void;
}

function AppContent({ isDemo, onLoginClick }: AppContentProps) {
  const { auth, logout } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [contextItems, setContextItems] = useState<DatasheetContextItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [theme, setTheme] = useState<ThemeType>(() => initTheme());
  const [activeMode, setActiveMode] = useState<HarveyMode>("sendgrid-2025");
  const [activePresetId, setActivePresetId] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    if (typeof window !== "undefined") {
      window.localStorage.setItem("pricing-theme", theme);
    }
  }, [theme]);

  const isSubmitDisabled =
    isLoading || !question.trim() || (auth!.role === "student" && !auth!.apiKey);

  const needsUpload = (item: DatasheetContextItem) =>
    item.kind === "yaml" && (item.origin === "user" || item.origin === "preset");

  const createContextItems = (inputs: ContextInputType[]): DatasheetContextItem[] =>
    inputs
      .map((item) => ({ ...item, value: item.value.trim(), id: crypto.randomUUID() }))
      .filter(
        (item) =>
          !contextItems.some(
            (existing) => existing.kind === item.kind && existing.value === item.value
          )
      );

  const addContextItems = (inputs: ContextInputType[]) => {
    if (inputs.length === 0) return null;
    const newItems = createContextItems(inputs);

    if (!isDemo) {
      const uploadPromises = newItems
        .filter(needsUpload)
        .map((item) => uploadDatasheet(`${item.id}.yaml`, item.value, auth!.credentials));

      if (uploadPromises.length > 0) {
        Promise.all(uploadPromises).catch((err) => console.error("Upload failed", err));
      }
    }

    setContextItems((prev) => [...prev, ...newItems]);
    return newItems;
  };

  const addContextItem = (input: ContextInputType) => {
    addContextItems([input]);
  };

  const removeContextItem = (id: string) => {
    if (!isDemo) {
      const toDelete = contextItems.filter((item) => item.id === id && needsUpload(item));
      toDelete.forEach((item) =>
        deleteDatasheet(`${item.id}.yaml`, auth!.credentials).catch(() => {})
      );
    }
    setContextItems((prev) => prev.filter((item) => item.id !== id));
  };

  const clearContext = () => {
    if (!isDemo) {
      contextItems
        .filter(needsUpload)
        .forEach((item) =>
          deleteDatasheet(`${item.id}.yaml`, auth!.credentials).catch(() => {})
        );
    }
    setContextItems([]);
  };

  const toggleTheme = () => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  };

  const handleFilesSelected = (files: FileList | null) => {
    if (!files || files.length === 0) return;

    Promise.all(
      Array.from(files).map((file) =>
        file.text().then((content) => ({ name: file.name, content }))
      )
    )
      .then((results) => {
        const inputs: ContextInputType[] = results
          .filter((r) => Boolean(r.content.trim()))
          .map((r) => ({ kind: "yaml", label: r.name, value: r.content, origin: "user" }));

        if (inputs.length > 0) addContextItems(inputs);

        if (inputs.length !== results.length) {
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: "assistant",
              content: "One or more uploaded files were empty and were skipped.",
              createdAt: new Date().toISOString(),
            },
          ]);
        }
      })
      .catch(() => {
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            content: "Could not read the uploaded file. Please try again.",
            createdAt: new Date().toISOString(),
          },
        ]);
      });
  };

  const handlePromptSelect = (preset: PromptPreset) => {
    setQuestion(preset.question);
    if (preset.context.length > 0) {
      addContextItems(
        preset.context.map((entry) => ({
          kind: entry.kind,
          label: entry.label,
          value: entry.value,
          origin: "preset",
        }))
      );
    }
  };

  const buildModeContextItem = (mode: Exclude<HarveyMode, "general">): DatasheetContextItem => {
    const { label, url } = MODE_DATASHEET[mode];
    return {
      id: crypto.randomUUID(),
      kind: "yaml-url",
      label,
      value: url,
      origin: "preset",
    };
  };

  const handleModeChange = (mode: HarveyMode) => {
    if (mode === activeMode) return;

    if (!isDemo) {
      contextItems
        .filter(needsUpload)
        .forEach((item) =>
          deleteDatasheet(`${item.id}.yaml`, auth!.credentials).catch(() => {})
        );
    }

    setMessages([]);
    setQuestion("");
    setActiveMode(mode);
    setActivePresetId(null);
    setContextItems([buildModeContextItem(mode)]);
  };

  const handleNewConversation = () => {
    setMessages([]);
    setQuestion("");
    setActivePresetId(null);
    setIsLoading(false);

    if (!isDemo) {
      contextItems
        .filter(needsUpload)
        .forEach((item) =>
          deleteDatasheet(`${item.id}.yaml`, auth!.credentials).catch(() => {})
        );
    }
    setContextItems((prev) => prev.filter((item) => item.kind === "yaml-url"));
  };

  const handleDemoPresetClick = (preset: PromptPreset) => {
    setActivePresetId(preset.id);
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: preset.question,
      createdAt: new Date().toISOString(),
    };
    const assistantMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: preset.demoResponse ?? DEMO_FALLBACK_RESPONSE,
      createdAt: new Date().toISOString(),
    };
    setMessages([userMessage, assistantMessage]);
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (isSubmitDisabled) return;

    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) return;

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmedQuestion,
      createdAt: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const requestBody: ChatRequest = {
        question: trimmedQuestion,
        history: messages.map((message) => ({
          role: message.role,
          content: message.content,
        })),
        ...(auth!.role === "student" && { api_key: auth!.apiKey }),
        ...buildChatPayload(contextItems),
      };
      const data = await chatWithAgent(requestBody, auth!.credentials);

      const chartHtml: string | undefined =
        typeof data?.result?.payload?.html === "string"
          ? data.result.payload.html
          : undefined;

      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.answer ?? "No response available.",
          createdAt: new Date().toISOString(),
          chartHtml,
          metadata: {
            plan: data.plan ?? undefined,
            result: data.result ?? undefined,
          },
        },
      ]);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `Error: ${(error as Error).message}`,
          createdAt: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsLoading(false);
      setQuestion("");
    }
  };

  const modeLabel = MODES.find((m) => m.id === activeMode)?.label ?? "H.A.R.V.E.Y.";

  return (
    <PricingContext.Provider value={contextItems}>
      <ThemeContext.Provider value={theme}>
        <div className="app">
          <header className="header-bar">
            <div>
              <h1>
                H.A.R.V.E.Y. <span className="mode-badge">{modeLabel}</span>
              </h1>
              <p>Analysing the {modeLabel} API — datasheet pre-loaded and locked.</p>
            </div>
            <div className="header-actions">
              {isDemo ? (
                <>
                  <span className="demo-badge">DEMO</span>
                  <button
                    type="button"
                    className="login-cta"
                    onClick={onLoginClick}
                  >
                    Log in
                  </button>
                </>
              ) : (
                <>
                  <span className="header-user">
                    {auth!.username}
                    {auth!.role === "student" && " · GEMINI"}
                  </span>
                  <ModeSettingsButton />
                  <button
                    type="button"
                    className="session-reset"
                    onClick={handleNewConversation}
                    disabled={isLoading}
                  >
                    New conversation
                  </button>
                  <button
                    type="button"
                    className="session-reset"
                    onClick={logout}
                    disabled={isLoading}
                  >
                    Log out
                  </button>
                </>
              )}
              <button
                type="button"
                className="theme-toggle"
                onClick={toggleTheme}
                aria-label="Toggle color theme"
              >
                {theme === "dark" ? "☀️ Switch to light mode" : "🌙 Switch to dark mode"}
              </button>
            </div>
          </header>

          {isDemo && (
            <div className="demo-banner">
              <span>
                <strong>Demo mode</strong> — Select a preset question to explore H.A.R.V.E.Y.
                Answers are illustrative. Log in to get real-time AI responses.
              </span>
              <button type="button" className="demo-banner-login" onClick={onLoginClick}>
                Log in →
              </button>
            </div>
          )}

          {!isDemo && (
            <ModeNav
              activeMode={activeMode}
              onModeChange={handleModeChange}
              disabled={isLoading}
            />
          )}

          <main className={isDemo && messages.length === 0 ? "main--demo-welcome" : ""}>
            <section className="chat-panel">
              <ChatTranscript
                messages={messages}
                isLoading={isLoading}
                promptPresets={MODE_PRESETS[activeMode as HarveyMode] ?? []}
                onPresetSelect={isDemo ? handleDemoPresetClick : handlePromptSelect}
                isDemo={isDemo}
              />
            </section>
            {(!isDemo || messages.length > 0) && (
              <section className="control-panel">
                {isDemo ? (
                  <DemoPresetPanel
                    presets={MODE_PRESETS[activeMode as HarveyMode] ?? []}
                    activePresetId={activePresetId}
                    onSelect={handleDemoPresetClick}
                  />
                ) : (
                  <ControlPanel
                    question={question}
                    contextItems={contextItems}
                    isSubmitting={isLoading}
                    isSubmitDisabled={isSubmitDisabled}
                    lockContext
                    onQuestionChange={setQuestion}
                    onSubmit={handleSubmit}
                    onFileSelect={handleFilesSelected}
                    onContextAdd={addContextItem}
                    onContextRemove={removeContextItem}
                    onContextClear={clearContext}
                  />
                )}
              </section>
            )}
          </main>
        </div>
      </ThemeContext.Provider>
    </PricingContext.Provider>
  );
}

function App() {
  const { auth } = useAuth();
  const [showLogin, setShowLogin] = useState(false);

  // Hide login page automatically after successful login
  useEffect(() => {
    if (auth) setShowLogin(false);
  }, [auth]);

  if (showLogin && !auth) return <LoginPage onBack={() => setShowLogin(false)} />;
  if (auth?.role === "student" && !auth.apiKey) return <ApiKeySetup />;

  return <AppContent isDemo={!auth} onLoginClick={() => setShowLogin(true)} />;
}

export default App;
