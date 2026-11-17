import axios from 'axios';

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

function describeError(error) {
  const data = error.response?.data;
  if (data?.error) {
    if (typeof data.error === 'string') return data.error;
    // DRF field errors: { field: ["msg"] }
    return Object.values(data.error).flat().join(' ');
  }
  if (data?.message) return data.message;
  if (error.code === 'ECONNABORTED') return 'The request timed out. Please try again.';
  if (!error.response) return 'Cannot reach the server. Is the Django backend running?';
  return 'Unexpected error while sending the message.';
}

export async function sendMessage(phoneNumber, message) {
  try {
    const { data } = await client.post('/send-message/', {
      phone_number: phoneNumber,
      message,
    });
    return data;
  } catch (error) {
    throw new Error(describeError(error));
  }
}
