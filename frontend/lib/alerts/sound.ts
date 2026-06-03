/**
 * Audible alert chime via the Web Audio API.
 *
 * No asset file — the beep is synthesized with an oscillator + gain envelope,
 * so there's nothing to host and nothing to 404. Tone-dependent: `info` is a
 * single soft note, `warning` a sharper note, `danger` a rising two-note pair.
 *
 * Browsers block audio until the page has seen a user gesture (autoplay
 * policy). `installAudioUnlock()` arms one-time listeners that resume the
 * AudioContext on the first interaction; the alerts panel toggle also calls
 * `unlockAudio()` directly so flipping sound on counts as that gesture.
 */
import type { AlertTone } from "./types";

let ctx: AudioContext | null = null;

function getCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  if (ctx === null) ctx = new Ctor();
  return ctx;
}

/** Resume the AudioContext. Safe to call repeatedly; must run on a gesture. */
export function unlockAudio(): void {
  const c = getCtx();
  if (c && c.state === "suspended") void c.resume();
}

let unlockInstalled = false;
const GESTURES = ["pointerdown", "keydown", "touchstart", "click"] as const;

/**
 * Arm global listeners that unlock audio on user gestures.
 *
 * Not `once`: some browsers leave the context suspended on the very first
 * `resume()` attempt, so we keep listening across gestures and only detach
 * once the context is actually `running` — otherwise a flaky first try would
 * silently disarm us forever.
 */
export function installAudioUnlock(): void {
  if (unlockInstalled || typeof window === "undefined") return;
  unlockInstalled = true;
  const handler = () => {
    unlockAudio();
    if (ctx?.state === "running") {
      for (const evt of GESTURES) window.removeEventListener(evt, handler);
    }
  };
  for (const evt of GESTURES) {
    window.addEventListener(evt, handler, { passive: true });
  }
}

/** One oscillator note with a click-free attack/decay envelope. */
function beep(
  c: AudioContext,
  freq: number,
  startAt: number,
  durationS: number,
  peak: number,
  type: OscillatorType = "sine",
): void {
  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0.0001, startAt);
  gain.gain.exponentialRampToValueAtTime(peak, startAt + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, startAt + durationS);
  osc.connect(gain).connect(c.destination);
  osc.start(startAt);
  osc.stop(startAt + durationS + 0.02);
}

function emit(c: AudioContext, tone: AlertTone): void {
  const t = c.currentTime;
  if (tone === "danger") {
    beep(c, 988, t, 0.14, 0.28, "triangle");
    beep(c, 1319, t + 0.16, 0.16, 0.28, "triangle");
  } else if (tone === "warning") {
    beep(c, 880, t, 0.16, 0.24, "triangle");
  } else {
    beep(c, 660, t, 0.12, 0.18, "sine");
  }
}

/** Play the chime for a given tone. No-op if audio is unavailable/locked. */
export function playAlertSound(tone: AlertTone): void {
  const c = getCtx();
  if (!c) return;
  if (c.state === "running") {
    emit(c, tone);
  } else {
    // Suspended: a gesture may have just armed it — play once resume resolves.
    // If no gesture ever happened, resume() never settles and we stay silent.
    void c.resume().then(() => {
      if (c.state === "running") emit(c, tone);
    });
  }
}
