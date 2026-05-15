"use client";

import { cn } from "@/lib/utils";
import type { RiveParameters } from "@rive-app/react-webgl2";
import {
  EventType,
  useRive,
  useStateMachineInput,
} from "@rive-app/react-webgl2";
import type { FC } from "react";
import { memo, useEffect, useMemo, useRef, useState } from "react";

// Delays Rive initialization by one frame so that React Strict Mode's
// throw-away mount in development doesn't immediately spin up a runtime
// instance we are about to discard.
const useStrictModeSafeInit = () => {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const id = requestAnimationFrame(() => setReady(true));
    return () => {
      cancelAnimationFrame(id);
      setReady(false);
    };
  }, []);

  return ready;
};

export type PersonaState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "asleep";

interface PersonaProps {
  state: PersonaState;
  onLoad?: RiveParameters["onLoad"];
  onLoadError?: RiveParameters["onLoadError"];
  onReady?: () => void;
  onPause?: RiveParameters["onPause"];
  onPlay?: RiveParameters["onPlay"];
  onStop?: RiveParameters["onStop"];
  className?: string;
  variant?: keyof typeof sources;
}

// The state machine name is always 'default' for Elements AI visuals
const stateMachine = "default";

const sources = {
  command: {
    dynamicColor: true,
    hasModel: true,
    source:
      "https://ejiidnob33g9ap1r.public.blob.vercel-storage.com/command-2.0.riv",
  },
  glint: {
    dynamicColor: true,
    hasModel: true,
    source:
      "https://ejiidnob33g9ap1r.public.blob.vercel-storage.com/glint-2.0.riv",
  },
  halo: {
    dynamicColor: true,
    hasModel: true,
    source:
      "https://ejiidnob33g9ap1r.public.blob.vercel-storage.com/halo-2.0.riv",
  },
  mana: {
    dynamicColor: false,
    hasModel: true,
    source:
      "https://ejiidnob33g9ap1r.public.blob.vercel-storage.com/mana-2.0.riv",
  },
  obsidian: {
    dynamicColor: true,
    hasModel: true,
    source:
      "https://ejiidnob33g9ap1r.public.blob.vercel-storage.com/obsidian-2.0.riv",
  },
  opal: {
    dynamicColor: false,
    hasModel: false,
    source:
      "https://ejiidnob33g9ap1r.public.blob.vercel-storage.com/orb-1.2.riv",
  },
};

export const Persona: FC<PersonaProps> = memo(
  ({
    variant = "obsidian",
    state = "idle",
    onLoad,
    onLoadError,
    onReady,
    onPause,
    onPlay,
    onStop,
    className,
  }) => {
    const source = sources[variant];

    if (!source) {
      throw new Error(`Invalid variant: ${variant}`);
    }

    // Stabilize callbacks to prevent useRive from reinitializing
    const callbacksRef = useRef({
      onLoad,
      onLoadError,
      onPause,
      onPlay,
      onReady,
      onStop,
    });

    useEffect(() => {
      callbacksRef.current = {
        onLoad,
        onLoadError,
        onPause,
        onPlay,
        onReady,
        onStop,
      };
    }, [onLoad, onLoadError, onPause, onPlay, onReady, onStop]);

    const stableCallbacks = useMemo(
      () => ({
        onLoad: ((loadedRive) =>
          callbacksRef.current.onLoad?.(
            loadedRive
          )) as RiveParameters["onLoad"],
        onLoadError: ((err) =>
          callbacksRef.current.onLoadError?.(
            err
          )) as RiveParameters["onLoadError"],
        onPause: ((event) =>
          callbacksRef.current.onPause?.(event)) as RiveParameters["onPause"],
        onPlay: ((event) =>
          callbacksRef.current.onPlay?.(event)) as RiveParameters["onPlay"],
        onReady: () => callbacksRef.current.onReady?.(),
        onStop: ((event) =>
          callbacksRef.current.onStop?.(event)) as RiveParameters["onStop"],
      }),
      []
    );

    // Delay initialisation by one frame to avoid work during Strict Mode's
    // first throw-away mount and keep the runtime instance stable.
    const ready = useStrictModeSafeInit();
    const riveParams = useMemo<Partial<Omit<RiveParameters, "canvas">> | null>(
      () =>
        ready
          ? {
              autoplay: true,
              onLoad: stableCallbacks.onLoad,
              onLoadError: stableCallbacks.onLoadError,
              onPause: stableCallbacks.onPause,
              onPlay: stableCallbacks.onPlay,
              onRiveReady: stableCallbacks.onReady,
              onStop: stableCallbacks.onStop,
              src: source.source,
              stateMachines: stateMachine,
            }
          : null,
      [ready, source.source, stableCallbacks]
    );

    const { rive, RiveComponent } = useRive(
      riveParams,
      {
        // Let the runtime size the canvas CSS box correctly and use the
        // device pixel ratio so the small avatar stays sharp.
        useDevicePixelRatio: true,
        useOffscreenRenderer: true,
      }
    );

    const listeningInput = useStateMachineInput(
      rive,
      stateMachine,
      "listening"
    );
    const thinkingInput = useStateMachineInput(rive, stateMachine, "thinking");
    const speakingInput = useStateMachineInput(rive, stateMachine, "speaking");
    const asleepInput = useStateMachineInput(rive, stateMachine, "asleep");

    // Rive state machine inputs are mutable objects that must be set via direct
    // property assignment — this is the intended Rive API, not a React anti-pattern.
    useEffect(() => {
      if (listeningInput) {
        listeningInput.value = state === "listening";
      }
      if (thinkingInput) {
        thinkingInput.value = state === "thinking";
      }
      if (speakingInput) {
        speakingInput.value = state === "speaking";
      }
      if (asleepInput) {
        asleepInput.value = state === "asleep";
      }
    }, [state, listeningInput, thinkingInput, speakingInput, asleepInput]);

    useEffect(() => {
      if (!rive) {
        return;
      }

      const syncRenderLoop = () => {
        if (document.hidden || state === "asleep") {
          rive.stopRendering();
        } else {
          rive.startRendering();
        }
      };

      const handleLoad = () => syncRenderLoop();
      const handleVisibilityChange = () => syncRenderLoop();

      syncRenderLoop();
      rive.on(EventType.Load, handleLoad);
      document.addEventListener("visibilitychange", handleVisibilityChange);

      return () => {
        rive.off(EventType.Load, handleLoad);
        document.removeEventListener("visibilitychange", handleVisibilityChange);
      };
    }, [rive, state]);

    return (
      <div className={cn("size-16 shrink-0", className)}>
        <RiveComponent />
      </div>
    );
  }
);

Persona.displayName = "Persona";
