import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { AuthProvider } from './context/authContext';
import { AppModeProvider } from './context/appModeContext';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <AuthProvider>
      <AppModeProvider>
        <App />
      </AppModeProvider>
    </AuthProvider>
  </React.StrictMode>
);
