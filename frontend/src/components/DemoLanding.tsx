interface Props {
  onSelectHarvey: () => void;
  onSelectPrime4Api: () => void;
  onLoginClick: () => void;
}

function DemoLanding({ onSelectHarvey, onSelectPrime4Api, onLoginClick }: Props) {
  return (
    <div className="demo-landing">
      <header className="demo-landing-header">
        <div className="demo-landing-icon">⚡</div>
        <h1 className="demo-landing-title">Pricing Intelligence Platform</h1>
        <p className="demo-landing-subtitle">
          Choose your demo experience below, or log in for full access.
        </p>
        <button type="button" className="login-cta" onClick={onLoginClick}>
          Log in →
        </button>
      </header>

      <div className="demo-landing-cards">
        <button type="button" className="demo-landing-card" onClick={onSelectHarvey}>
          <span className="demo-landing-card-icon">💬</span>
          <h2 className="demo-landing-card-title">H.A.R.V.E.Y. Demo</h2>
          <p className="demo-landing-card-desc">
            AI assistant for pricing intelligence. Ask natural-language questions about API
            plans, quotas, and rate limits — and get instant structured answers.
          </p>
          <span className="demo-landing-card-cta">Try Harvey →</span>
        </button>

        <button type="button" className="demo-landing-card" onClick={onSelectPrime4Api}>
          <span className="demo-landing-card-icon">🔬</span>
          <h2 className="demo-landing-card-title">PRIME4API Playground</h2>
          <p className="demo-landing-card-desc">
            Ground-truth testing interface for the PRIME4API pricing engine.
          </p>
          <span className="demo-landing-card-cta">Try PRIME4API →</span>
        </button>
      </div>
    </div>
  );
}

export default DemoLanding;
