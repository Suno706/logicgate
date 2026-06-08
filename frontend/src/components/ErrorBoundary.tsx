import { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props { children: ReactNode }
interface State { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="h-screen flex items-center justify-center bg-bg-900">
        <div className="bg-bg-800 border border-err/30 rounded-xl p-8 max-w-md w-full mx-4 space-y-4">
          <div className="flex items-center gap-3">
            <AlertTriangle size={20} className="text-err" />
            <h2 className="text-sm font-mono font-bold text-err">Rendering error</h2>
          </div>
          <p className="text-xs font-mono text-gray-400 leading-relaxed break-all">
            {this.state.error.message}
          </p>
          <button
            onClick={() => this.setState({ error: null })}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-bg-700 hover:bg-bg-600 border border-bg-600 text-xs font-mono text-gray-300 transition-colors"
          >
            <RefreshCw size={12} />
            Try again
          </button>
        </div>
      </div>
    );
  }
}
