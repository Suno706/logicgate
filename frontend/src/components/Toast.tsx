import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { CheckCircle, XCircle, AlertTriangle, Info, X } from "lucide-react";

type ToastVariant = "success" | "error" | "warning" | "info";

interface ToastItem {
  id: string;
  message: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  add: (message: string, variant?: ToastVariant) => void;
}

const ToastCtx = createContext<ToastContextValue>({ add: () => {} });

const ICONS: Record<ToastVariant, React.ReactNode> = {
  success: <CheckCircle size={14} className="text-ok flex-shrink-0" />,
  error:   <XCircle    size={14} className="text-err flex-shrink-0" />,
  warning: <AlertTriangle size={14} className="text-warn flex-shrink-0" />,
  info:    <Info       size={14} className="text-accent flex-shrink-0" />,
};

const BORDER: Record<ToastVariant, string> = {
  success: "border-ok/30",
  error:   "border-err/30",
  warning: "border-warn/30",
  info:    "border-accent/30",
};

function ToastItem({ item, onDismiss }: { item: ToastItem; onDismiss: (id: string) => void }) {
  useEffect(() => {
    const t = setTimeout(() => onDismiss(item.id), 3500);
    return () => clearTimeout(t);
  }, [item.id, onDismiss]);

  return (
    <div
      className={`flex items-center gap-2.5 bg-bg-800 border ${BORDER[item.variant]} rounded-lg px-3 py-2.5 shadow-xl shadow-black/40 min-w-[220px] max-w-[320px] animate-in`}
      style={{ animation: "slideIn 0.15s ease-out" }}
    >
      {ICONS[item.variant]}
      <span className="text-xs font-mono text-gray-200 flex-1 leading-snug">{item.message}</span>
      <button
        onClick={() => onDismiss(item.id)}
        className="text-gray-600 hover:text-gray-300 transition-colors ml-1 flex-shrink-0"
        aria-label="Dismiss"
      >
        <X size={12} />
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const add = useCallback((message: string, variant: ToastVariant = "info") => {
    const id = `toast-${++counter.current}`;
    setToasts((prev) => [...prev.slice(-4), { id, message, variant }]);
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastCtx.Provider value={{ add }}>
      {children}
      <div className="fixed bottom-6 right-4 z-[200] flex flex-col gap-2 items-end pointer-events-none">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto">
            <ToastItem item={t} onDismiss={dismiss} />
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const { add } = useContext(ToastCtx);
  return {
    success: (msg: string) => add(msg, "success"),
    error:   (msg: string) => add(msg, "error"),
    warning: (msg: string) => add(msg, "warning"),
    info:    (msg: string) => add(msg, "info"),
  };
}
