/**
 * Notification delivery — browser Notification API + in-app toast (sonner).
 *
 * Notification permission is requested by the user from the alerts panel.
 * The toast always fires; the desktop notification only when permission is
 * granted AND the user toggled it on.
 */
import { toast } from "sonner";
import { playAlertSound } from "./sound";
import type { AlertEvent } from "./types";

export function notifyAlert(event: AlertEvent, desktopEnabled: boolean, soundEnabled: boolean): void {
  const fn = event.tone === "danger" ? toast.error : event.tone === "warning" ? toast.warning : toast.info;
  fn(event.title, { description: event.detail, duration: 8000 });

  if (soundEnabled) playAlertSound(event.tone);

  if (
    desktopEnabled &&
    typeof window !== "undefined" &&
    "Notification" in window &&
    Notification.permission === "granted"
  ) {
    try {
      new Notification(event.title, {
        body: event.detail,
        tag: event.ruleId,
        icon: "/favicon.ico",
      });
    } catch (err) {
      console.warn("Notification dispatch failed", err);
    }
  }
}

export async function requestNotificationPermission(): Promise<boolean> {
  if (typeof window === "undefined" || !("Notification" in window)) {
    return false;
  }
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  const result = await Notification.requestPermission();
  return result === "granted";
}
