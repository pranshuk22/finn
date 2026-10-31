import { Component, type ReactNode } from "react";
import { clearSaved } from "../api";
import { Button } from "./ui";

/** A screen that throws while rendering shows a way out instead of a blank page. */
export class ScreenBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error("Screen failed to render", error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="mx-4 mt-16 rounded-[12px] border border-line p-5 text-center">
        <p className="text-ink">This screen could not be shown.</p>
        <p className="mt-1 text-[13px] text-muted">Reloading clears the copies saved on this device and fetches fresh data.</p>
        <Button
          kind="ghost"
          className="mt-4"
          onClick={() => {
            clearSaved();
            location.reload();
          }}
        >
          Reload
        </Button>
      </div>
    );
  }
}
