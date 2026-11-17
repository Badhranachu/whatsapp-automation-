import { useState } from 'react';
import { sendMessage } from '../services/api';
import StatusPanel from './StatusPanel';

const MAX_LENGTH = 4096;

function isValidPhone(value) {
  const digits = value.replace(/[\s\-().]/g, '').replace(/^\+/, '');
  return /^[1-9]\d{7,14}$/.test(digits);
}

export default function MessageForm() {
  const [phone, setPhone] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(null); // { type: 'success'|'error', text, id? }

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;

    if (!isValidPhone(phone)) {
      setStatus({ type: 'error', text: 'Enter a valid international phone number, e.g. +919876543210.' });
      return;
    }
    if (!message.trim()) {
      setStatus({ type: 'error', text: 'Message cannot be empty.' });
      return;
    }

    setLoading(true);
    setStatus(null);
    try {
      const data = await sendMessage(phone, message);
      if (data.success) {
        setStatus({ type: 'success', text: data.message, id: data.message_id });
        setPhone('');
        setMessage('');
      } else {
        setStatus({ type: 'error', text: data.error || data.message });
      }
    } catch (err) {
      setStatus({ type: 'error', text: err.message });
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setPhone('');
    setMessage('');
    setStatus(null);
  };

  return (
    <form onSubmit={handleSubmit} noValidate>
      <label htmlFor="phone">Recipient Phone Number</label>
      <input
        id="phone"
        type="tel"
        placeholder="+91 9876543210"
        value={phone}
        onChange={(e) => setPhone(e.target.value)}
        disabled={loading}
        autoComplete="off"
      />

      <label htmlFor="message">Message</label>
      <textarea
        id="message"
        rows={6}
        maxLength={MAX_LENGTH}
        placeholder="Enter your WhatsApp message here..."
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        disabled={loading}
      />
      <div className="counter">{message.length} characters</div>

      <div className="actions">
        <button type="submit" className="primary" disabled={loading}>
          {loading ? (
            <>
              <span className="spinner" aria-hidden="true" /> Sending...
            </>
          ) : (
            'Send Message'
          )}
        </button>
        <button type="button" className="secondary" onClick={handleReset} disabled={loading}>
          Clear
        </button>
      </div>

      <StatusPanel status={status} />
    </form>
  );
}
