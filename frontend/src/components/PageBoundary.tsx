import { Component, type ReactNode } from "react";
import { Button, Card } from "./ui";

export class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (!this.state.failed) return this.props.children;
    return <Card title="This page could not load"><p role="alert" className="mb-4 text-sm text-ink-2">The workspace is still available. Reload to get the latest application files, or choose another section from the navigation.</p><Button onClick={() => window.location.reload()}>Reload workspace</Button></Card>;
  }
}
