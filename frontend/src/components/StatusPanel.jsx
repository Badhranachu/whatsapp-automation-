export default function StatusPanel({ status }) {
  return (
    <section className="status-panel" aria-live="polite">
      <h2>Message Status</h2>
      {!status && <p className="muted">No message sent yet.</p>}
      {status?.type === 'success' && (
        <div className="status success">
          <strong>✓ {status.text}</strong>
          {status.id && <div className="msg-id">Message ID: {status.id}</div>}
          <div className="muted">Accepted by Meta for processing; delivery is not guaranteed.</div>
        </div>
      )}
      {status?.type === 'error' && (
        <div className="status error" role="alert">
          <strong>✗ {status.text}</strong>
        </div>
      )}
    </section>
  );
}
