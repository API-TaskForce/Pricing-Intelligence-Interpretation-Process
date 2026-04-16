import { FormEvent, useState } from "react";
import { useAuth } from "../context/authContext";

export default function ApiKeySetup() {
  const { auth, setApiConfig, logout } = useAuth();
  const [apiKey, setApiKey] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) return;
    setApiConfig(apiKey.trim());
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <h1>H.A.R.V.E.Y.</h1>
        <p className="login-subtitle">Bienvenido, {auth?.username}</p>
        <p className="login-subtitle">Introduce tu API Key de Google Gemini para continuar</p>

        <div className="api-key-info">
          <p>
            Consigue tu clave gratuita iniciando sesión en:
          </p>
          <a
            href="https://aistudio.google.com/app/api-keys"
            target="_blank"
            rel="noopener noreferrer"
            className="api-key-link"
          >
            aistudio.google.com/app/api-keys
          </a>
          <p className="api-key-format">
            Formato de la clave: <code>AQ...</code>
          </p>
          <p>
            Esta clave se usa solo durante tus pruebas en Harvey. Como buena
            práctica, cuando termines puedes revocarla desde Google AI Studio
            y crear una nueva en futuras sesiones.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          <div className="login-field">
            <label htmlFor="apiKey">API Key de Gemini</label>
            <input
              id="apiKey"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="AQ..."
              autoComplete="off"
            />
          </div>
          <button
            type="submit"
            className="login-submit"
            disabled={!apiKey.trim()}
          >
            Confirmar
          </button>
        </form>

        <button type="button" className="logout-link" onClick={logout}>
          Cerrar sesión
        </button>
      </div>
    </div>
  );
}
