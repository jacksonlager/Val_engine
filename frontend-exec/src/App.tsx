import { useEffect, useState } from "react";
import { loadView, type LoadState } from "./lib/data";
import { TopBar, Masthead } from "./sections/Masthead";
import { Headline } from "./sections/Headline";
import { Bridge } from "./sections/Bridge";
import { Movers } from "./sections/Movers";
import { Funds } from "./sections/Funds";
import { Composition } from "./sections/Composition";
import { Risk } from "./sections/Risk";
import { Activity } from "./sections/Activity";
import { Marks } from "./sections/Marks";
import { Footer } from "./sections/Footer";

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="max-w-page mx-auto px-8">{children}</div>;
}

function Notice({ title, body }: { title: string; body: React.ReactNode }) {
  return (
    <div className="min-h-[70vh] flex items-center justify-center">
      <div className="max-w-[48ch] text-center">
        <div className="eyebrow mb-3">Human Capital</div>
        <h1 className="display text-[28px] font-semibold text-ink leading-tight">{title}</h1>
        <p className="text-[14px] text-ink2 mt-3 leading-relaxed">{body}</p>
      </div>
    </div>
  );
}

export default function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  useEffect(() => {
    let alive = true;
    loadView().then((s) => alive && setState(s));
    return () => {
      alive = false;
    };
  }, []);

  if (state.kind === "loading") {
    return <Shell><div className="min-h-[70vh] flex items-center justify-center text-[13px] text-muted">Loading the latest published quarter…</div></Shell>;
  }
  if (state.kind === "empty") {
    return (
      <Shell>
        <Notice
          title="No quarter has been released yet."
          body={<>Marks are published from the review dashboard once the back office has confirmed them. <a href="/" className="whitespace-nowrap">Open the back-office review →</a></>}
        />
      </Shell>
    );
  }
  if (state.kind === "error") {
    return <Shell><Notice title="The valuation service could not be reached." body={<>{state.message} Reload once the service is back.</>} /></Shell>;
  }

  const view = state.view;
  return (
    <>
      <TopBar view={view} />
      <Shell>
        <Masthead view={view} />
        <Headline view={view} />
        <Bridge view={view} />
        <Movers view={view} />
        <Funds view={view} />
        <Composition view={view} />
        <Risk view={view} />
        <Activity view={view} />
        <Marks view={view} />
        <Footer view={view} />
      </Shell>
    </>
  );
}
