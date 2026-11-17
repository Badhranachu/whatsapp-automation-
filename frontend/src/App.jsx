import MessageForm from './components/MessageForm';
import './App.css';

export default function App() {
  return (
    <main className="card">
      <h1>WhatsApp Messenger</h1>
      <p className="subtitle">Send WhatsApp messages using Meta Cloud API.</p>
      <MessageForm />
    </main>
  );
}
