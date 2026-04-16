import { createContext, useContext, useState, ReactNode } from "react";

export type UserRole = "admin" | "student";

interface AuthState {
  username: string;
  role: UserRole;
  credentials: string; // base64(username:password) — sent as Authorization: Basic <credentials>
  apiKey: string;      // only used for students; empty string until set
}

interface AuthContextType {
  auth: AuthState | null;
  login: (username: string, role: UserRole, credentials: string) => void;
  logout: () => void;
  setApiConfig: (apiKey: string) => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState | null>(null);

  const login = (username: string, role: UserRole, credentials: string) => {
    setAuth({ username, role, credentials, apiKey: "" });
  };

  const logout = () => setAuth(null);

  const setApiConfig = (apiKey: string) => {
    setAuth((prev) => (prev ? { ...prev, apiKey } : null));
  };

  return (
    <AuthContext.Provider value={{ auth, login, logout, setApiConfig }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
