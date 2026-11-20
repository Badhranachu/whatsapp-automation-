import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import StageApp from './StageApp';
import './stage.css';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <StageApp />
  </StrictMode>,
);
