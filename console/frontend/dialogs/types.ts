export const DIALOG_EVENT = "comic:dialog";

export interface DialogOptions {
  title?: string;
  message?: string;
  kind?: string;
  confirmText?: string;
  cancelText?: string;
  prompt?: boolean;
  defaultValue?: string;
}

export interface NormalizedDialogOptions {
  title: string;
  message: string;
  kind: string;
  confirmText: string;
  cancelText: string;
  prompt: boolean;
  defaultValue: string;
}

export type DialogResult = boolean | string | null;

export interface DialogEventDetail {
  options: DialogOptions;
  resolve: (result: DialogResult) => void;
}

export interface DialogQueueItem {
  id: string;
  options: NormalizedDialogOptions;
  resolve: (result: DialogResult) => void;
  returnFocus: HTMLElement | null;
}

declare global {
  interface Window {
    comicDialog?: (options: DialogOptions) => Promise<DialogResult>;
  }
}
