import { Component, StrictMode } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './index.css';

interface BoundaryState {
  error: Error | null;
}

/**
 * Верхний предохранитель: белый экран в проде мы уже ловили,
 * теперь показываем текст ошибки и кнопку перезагрузки.
 */
class RootBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  override state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[rentkit] сбой рендера', error, info.componentStack);
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="mx-auto mt-16 max-w-lg px-4">
        <div className="card p-6">
          <h1 className="text-lg font-semibold text-slate-900">Витрина упала</h1>
          <p className="mt-2 text-sm text-slate-600">
            Мы уже записали ошибку в лог. Обновите страницу — черновик брони сохранится.
          </p>
          <pre className="mt-4 overflow-x-auto rounded-lg bg-slate-100 p-3 font-mono text-xs text-slate-700">
            {error.message}
          </pre>
          <button className="btn-primary mt-4" onClick={() => window.location.reload()}>
            Обновить страницу
          </button>
        </div>
      </div>
    );
  }
}

const container = document.getElementById('root');
if (!container) {
  throw new Error('Не найден #root — проверьте index.html');
}

createRoot(container).render(
  <StrictMode>
    <RootBoundary>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </RootBoundary>
  </StrictMode>,
);

// Необработанные промисы часто прилетают из api.ts при обрыве сети — логируем адресно
window.addEventListener('unhandledrejection', (event) => {
  console.warn('[rentkit] необработанный промис', event.reason);
});
