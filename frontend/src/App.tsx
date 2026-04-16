import { FormEvent, useEffect, useState } from "react";

import ChatTranscript from "./components/ChatTranscript";
import ControlPanel from "./components/ControlPanel";
import LoginPage from "./components/LoginPage";
import ApiKeySetup from "./components/ApiKeySetup";
import type {
  ChatMessage,
  DatasheetContextItem,
  PromptPreset,
  ContextInputType,
  ChatRequest,
} from "./types";
import { PROMPT_PRESETS } from "./prompts";
import { ThemeContext, ThemeType } from "./context/themeContext";
import {
  chatWithAgent,
  buildChatPayload,
  deleteDatasheet,
  uploadDatasheet,
} from "./utils";
import { PricingContext } from "./context/pricingContext";
import { useAuth } from "./context/authContext";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8086";

const initTheme = (): ThemeType => {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem("pricing-theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
};

function AppContent() {
  const { auth, logout } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [contextItems, setContextItems] = useState<DatasheetContextItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [theme, setTheme] = useState<ThemeType>(() => initTheme());

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    if (typeof window !== "undefined") {
      window.localStorage.setItem("pricing-theme", theme);
    }
  }, [theme]);

  const isSubmitDisabled =
    isLoading || !question.trim() || (auth.role === "student" && !auth.apiKey);

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

    const uploadPromises = newItems
      .filter((item) => item.origin === "user" || item.origin === "preset")
      .map((item) => uploadDatasheet(`${item.id}.yaml`, item.value, auth.credentials));

    if (uploadPromises.length > 0) {
      Promise.all(uploadPromises).catch((err) => console.error("Upload failed", err));
    }

    setContextItems((prev) => [...prev, ...newItems]);
    return newItems;
  };

  const addContextItem = (input: ContextInputType) => {
    addContextItems([input]);
  };

  const removeContextItem = (id: string) => {
    const toDelete = contextItems.filter(
      (item) => item.id === id && (item.origin === "user" || item.origin === "preset")
    );
    toDelete.forEach((item) =>
      deleteDatasheet(`${item.id}.yaml`, auth.credentials).catch(() => {})
    );
    setContextItems((prev) => prev.filter((item) => item.id !== id));
  };

  const clearContext = () => {
    contextItems
      .filter((item) => item.origin === "user" || item.origin === "preset")
      .forEach((item) =>
        deleteDatasheet(`${item.id}.yaml`, auth.credentials).catch(() => {})
      );
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

  const handleNewConversation = () => {
    setMessages([]);
    setQuestion("");
    setContextItems([]);
    setIsLoading(false);
  };

  const getUniqueYamls = () =>
    Array.from(new Set(contextItems.map((item) => item.value)));

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
        ...(auth.role === "student" && { api_key: auth.apiKey }),
        ...buildChatPayload(getUniqueYamls()),
      };
      const data = await chatWithAgent(requestBody, auth.credentials);

      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.answer ?? "No response available.",
          createdAt: new Date().toISOString(),
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

  return (
    <PricingContext.Provider value={contextItems}>
      <ThemeContext.Provider value={theme}>
        <div className="app">
          <header className="header-bar">
            <div>
              <h1>H.A.R.V.E.Y. API Analysis Assistant</h1>
              <p>
                Ask about API rate limits, quotas, and consumption using the
                Holistic Analysis and Regulation Virtual Expert for You (H.A.R.V.E.Y.) agent.
              </p>
            </div>
            <div className="header-actions">
              <span className="header-user">
                {auth.username}
                {auth.role === "student" && " · GEMINI"}
              </span>
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
          <main>
            <section className="chat-panel">
              <ChatTranscript
                messages={messages}
                isLoading={isLoading}
                promptPresets={PROMPT_PRESETS}
                onPresetSelect={handlePromptSelect}
              />
            </section>
            <section className="control-panel">
              <ControlPanel
                question={question}
                contextItems={contextItems}
                isSubmitting={isLoading}
                isSubmitDisabled={isSubmitDisabled}
                onQuestionChange={setQuestion}
                onSubmit={handleSubmit}
                onFileSelect={handleFilesSelected}
                onContextAdd={addContextItem}
                onContextRemove={removeContextItem}
                onContextClear={clearContext}
              />
            </section>
          </main>
        </div>
      </ThemeContext.Provider>
    </PricingContext.Provider>
  );
}

function App() {
  const { auth } = useAuth();

  if (!auth) return <LoginPage />;
  if (auth.role === "student" && !auth.apiKey) return <ApiKeySetup />;

  return <AppContent />;
}

export default App;
