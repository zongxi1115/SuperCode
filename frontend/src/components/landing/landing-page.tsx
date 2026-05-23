import { useEffect, useState } from "react";
import { Alignment, Fit, Layout, useRive } from "@rive-app/react-webgl2";

const LANDING_ARTBOARD = "Artboard";
const LANDING_STATE_MACHINE = "State Machine 1";

function LandingMascot() {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const frame = requestAnimationFrame(() => setReady(true));
    return () => {
      cancelAnimationFrame(frame);
      setReady(false);
    };
  }, []);

  const { RiveComponent } = useRive(
    ready
      ? {
          src: "/rive/ai-visual-assistant.riv",
          artboard: LANDING_ARTBOARD,
          stateMachines: LANDING_STATE_MACHINE,
          autoplay: true,
          layout: new Layout({
            fit: Fit.Cover,
            alignment: Alignment.Center,
          }),
        }
      : null,
    {
      useDevicePixelRatio: true,
      useOffscreenRenderer: true,
    }
  );

  return (
    <div className="landing-rive-shell" aria-hidden="true">
      <div className="landing-rive-frame">
        <RiveComponent />
      </div>
    </div>
  );
}

export function LandingPage() {
  const [prompt, setPrompt] = useState("");

  return (
    <main className="landing-stage">
      <LandingMascot />
      <section className="landing-input-anchor">
        <div className="landing-input-shell">
          <label className="sr-only" htmlFor="landing-prompt">
            描述你想构建的产品
          </label>
          <textarea
            id="landing-prompt"
            className="landing-input"
            placeholder="描述你想构建的产品，例如：一个支持登录、支付和管理后台的 SaaS 应用"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={4}
          />
        </div>
      </section>
    </main>
  );
}
