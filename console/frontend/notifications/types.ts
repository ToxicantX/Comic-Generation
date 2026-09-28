export const NOTIFICATION_EVENT = "comic:notify";

export type NotificationType = "info" | "success" | "warn" | "error";

export interface NotificationInput {
  message: string;
  type?: NotificationType;
  title?: string;
  durationMs?: number;
}

export interface NotificationItem {
  id: string;
  message: string;
  type: NotificationType;
  title: string;
  durationMs: number;
}

declare global {
  interface Window {
    comicNotify?: (notification: NotificationInput) => void;
    __comicPendingNotifications?: NotificationInput[];
  }
}
