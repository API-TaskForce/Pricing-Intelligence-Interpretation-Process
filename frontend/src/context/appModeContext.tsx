import { createContext, useContext, useState, ReactNode } from "react";

export type QueryMode = "guided" | "autonomous";

interface AppModeContextType {
  queryMode: QueryMode;
  setQueryMode: (mode: QueryMode) => void;
}

const AppModeContext = createContext<AppModeContextType>({
  queryMode: "guided",
  setQueryMode: () => {},
});

const STORAGE_KEY = "pricing-query-mode";

export function AppModeProvider({ children }: { children: ReactNode }) {
  const [queryMode, setQueryModeState] = useState<QueryMode>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "autonomous" ? "autonomous" : "guided";
  });

  const setQueryMode = (mode: QueryMode) => {
    setQueryModeState(mode);
    localStorage.setItem(STORAGE_KEY, mode);
  };

  return (
    <AppModeContext.Provider value={{ queryMode, setQueryMode }}>
      {children}
    </AppModeContext.Provider>
  );
}

export function useAppMode(): AppModeContextType {
  return useContext(AppModeContext);
}
